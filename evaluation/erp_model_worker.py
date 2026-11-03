"""Run one isolated ORM-agent benchmark question."""

from contextlib import ExitStack
import traceback
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
    if text.startswith(("orm read refused:", "query refused:")) or "failed or was refused" in text:
        return "invalid"
    return "ok"


def describe_tool_call(name, arguments, observation):
    """Benchmark record of a tool call: its arguments, and the error when it was refused or unknown."""
    from config import settings

    call = {"name": name, "status": classify_tool_observation(observation), "args": arguments}
    if call["status"] != "ok":
        call["error"] = str(observation)[:settings.OBSERVATION_PREVIEW_CHARS]
    return call


def run_question(question, uid, api_key, db, model, reasoning_effort, result_queue):
    """Execute one question and return only benchmark-safe metadata to the parent."""
    from config import settings
    from erp_data.odoo_context import request_identity
    import erp_data.orm_agent_helpers as helpers
    import erp_data.orm_agent_node as agent
    from evaluation.ollama_server import model_override
    from core.evidence import start_evidence_collection

    tool_calls = []
    llm_errors = []
    model_answers = []
    query_plans = []

    execute_tool_call = agent.execute_tool_call
    invoke_llm = agent.invoke_llm
    helper_invoke_llm = helpers.invoke_llm
    build_response = agent._build_response

    def tracked_tool_call(tool_call, all_tools, plan=None):
        name, arguments, observation, coverage_complete = execute_tool_call(tool_call, all_tools, plan)
        call = describe_tool_call(name, arguments, observation)
        tool_calls.append(call)
        result_queue.put({"event": "tool_call", "call": call})
        return name, arguments, observation, coverage_complete

    def tracked_build_response(question, result):
        model_answers.append(result.answer)
        return build_response(question, result)

    plan_orm_question = agent.plan_orm_question

    def tracked_plan(*args, **kwargs):
        plan, calls = plan_orm_question(*args, **kwargs)
        serialized_plan = plan.model_dump() if plan is not None else None
        query_plans.append(serialized_plan)
        result_queue.put({"event": "query_plan", "plan": serialized_plan})
        return plan, calls

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
            stack.enter_context(patch.object(agent, "plan_orm_question", tracked_plan))
            stack.enter_context(patch.object(
                agent, "invoke_llm", lambda *args, **kwargs: tracked_invoke(invoke_llm, *args, **kwargs)))
            stack.enter_context(patch.object(agent, "_build_response", tracked_build_response))
            stack.enter_context(patch.object(agent, "ReasoningTraceLogger", _SilentTraceLogger))
            stack.enter_context(patch.object(settings, "ERP_REASONING_EFFORT", reasoning_effort))
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
            "model_answer": model_answers[0] if model_answers else None,
            "query_plan": query_plans[0] if query_plans else None,
            "timing": result.get("timing", {}),
            "tool_calls": tool_calls,
            "llm_errors": llm_errors,
        }})
    except Exception as error:
        result_queue.put({"event": "result", "result": {
            "worker_error": type(error).__name__,
            "worker_error_detail": str(error)[:500],
            "worker_traceback": traceback.format_exc(limit=8)[:4000],
            "query_plan": query_plans[0] if query_plans else None,
            "tool_calls": tool_calls,
            "llm_errors": llm_errors,
        }})
