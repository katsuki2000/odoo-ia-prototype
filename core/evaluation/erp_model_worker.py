"""Run one isolated ORM-agent benchmark question."""

from contextlib import ExitStack
from unittest.mock import patch


class _SilentTraceLogger:
    def log_hop(self, *args, **kwargs):
        pass

    def log_summary(self, *args, **kwargs):
        pass


def classify_tool_observation(observation):
    text = str(observation).casefold()
    if text.startswith("tool '") and " is not available." in text:
        return "unknown"
    if text.startswith("orm read refused:") or "failed or was refused" in text:
        return "invalid"
    return "ok"


def run_question(question, uid, api_key, db, model, result_queue):
    """Execute one question and return only benchmark-safe metadata to the parent."""
    from erp_data.odoo_context import request_identity
    import erp_data.orm_agent_helpers as helpers
    import erp_data.orm_agent_node as agent
    from core.evaluation.ollama_server import model_override
    from core.evidence import start_evidence_collection

    tool_calls = []
    llm_errors = []

    execute_tool_call = agent.execute_tool_call
    invoke_llm = agent.invoke_llm
    helper_invoke_llm = helpers.invoke_llm

    def tracked_tool_call(tool_call, all_tools):
        name, arguments, observation = execute_tool_call(tool_call, all_tools)
        call = {"name": name, "status": classify_tool_observation(observation)}
        tool_calls.append(call)
        result_queue.put({"event": "tool_call", "call": call})
        return name, arguments, observation

    def tracked_invoke(invoke, *args, **kwargs):
        result_queue.put({"event": "llm_call"})
        try:
            return invoke(*args, **kwargs)
        except Exception as error:
            error_info = {"module": type(error).__module__, "type": type(error).__name__}
            llm_errors.append(error_info)
            result_queue.put({"event": "llm_error", "error": error_info})
            raise

    try:
        with ExitStack() as stack:
            stack.enter_context(request_identity(uid, api_key, db=db))
            stack.enter_context(patch.object(agent, "execute_tool_call", tracked_tool_call))
            stack.enter_context(patch.object(
                agent, "invoke_llm", lambda *args, **kwargs: tracked_invoke(invoke_llm, *args, **kwargs)))
            stack.enter_context(patch.object(agent, "ReasoningTraceLogger", _SilentTraceLogger))
            stack.enter_context(patch.object(
                helpers, "invoke_llm", lambda *args, **kwargs: tracked_invoke(helper_invoke_llm, *args, **kwargs)))
            start_evidence_collection()
            with model_override(model):
                result = agent.orm_agent_loop({
                    "question": question,
                    "chat_history": [],
                    "uid": uid,
                    "timing": {},
                })
        response = result.get("response")
        result_queue.put({"event": "result", "result": {
            "answer": response.answer if response else "",
            "timing": result.get("timing", {}),
            "tool_calls": tool_calls,
            "llm_errors": llm_errors,
        }})
    except Exception as error:
        result_queue.put({"event": "result", "result": {
            "worker_error": type(error).__name__,
            "tool_calls": tool_calls,
            "llm_errors": llm_errors,
        }})
