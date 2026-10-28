"""
orm_agent_node.py

ORM ReAct agent loop (ERP data queries) and hybrid pipeline node.
"""

import logging
import time

from langchain_core.messages import HumanMessage, ToolMessage

from core.schemas import AssistantResponse, SourceReference
from config.settings import MASSIVE_EXTRACTION_REFUSAL_MSG, PROMPT_INJECTION_REFUSAL_MSG
from core.guardrails import (
    OUT_OF_SCOPE_ANSWER, REACT_RECURSION_LIMIT, is_massive_extraction_request, is_out_of_scope, is_prompt_injection,
)
from core.state import RAGState
from document_rag.generate_node import generate
from core.llm.llm_client import invoke_with_rate_limit as _invoke_with_rate_limit
from core.session.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id

from erp_data.orm_agent_helpers import (
    _build_llm,
    resolve_orm_tools,
    recover_malformed_tool_call,
    execute_tool_call,
    force_final_synthesis,
)

logger = logging.getLogger(__name__)


def orm_agent_loop(state: RAGState) -> dict:
    """ReAct agent loop: Reason -> call ORM tool -> observe -> repeat or answer."""
    start_time = time.time()
    question = state["question"]
    chat_history = state.get("chat_history", [])
    logger.info("Node [orm_agent_loop]: Starting ReAct loop for: %s", question)

    _trace_id = new_trace_id()
    _trace_logger = ReasoningTraceLogger()
    _llm_call_count = 0
    _hop_index = 0

    refusal = (OUT_OF_SCOPE_ANSWER if is_out_of_scope(question) else
               PROMPT_INJECTION_REFUSAL_MSG if is_prompt_injection(question) else
               MASSIVE_EXTRACTION_REFUSAL_MSG if is_massive_extraction_request(question) else None)
    if refusal:
        logger.info("Node [orm_agent_loop]: Early refusal (out of scope, prompt injection or massive extraction).")
        response = AssistantResponse(answer=refusal, sources=[], confidence=0.0)
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="donnees_erp", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    skills = state.get("skills", {})
    all_tools = resolve_orm_tools(skills)

    llm = _build_llm(temperature=0.0, max_retries=0)
    _tool_llm_box = [llm.bind_tools(all_tools)]

    def _rebuild_tool_llm():
        fresh = _build_llm(temperature=0.0, max_retries=0)
        _tool_llm_box[0] = fresh.bind_tools(all_tools)
        return _tool_llm_box[0]

    from erp_data.prompts import build_orm_agent_messages
    messages = build_orm_agent_messages(question, chat_history)

    tool_observations = []
    final_answer = None

    for iteration in range(REACT_RECURSION_LIMIT):
        logger.info("Node [orm_agent_loop]: Iteration %d/%d", iteration + 1, REACT_RECURSION_LIMIT)

        try:
            ai_msg, _wait = _invoke_with_rate_limit(
                _tool_llm_box[0], messages, rebuild_llm=_rebuild_tool_llm,
            )
            _llm_call_count += 1
        except Exception as e:
            _llm_call_count += 1
            logger.warning("LLM invoke failed at iteration %d: %s", iteration + 1, e)

            recovered = recover_malformed_tool_call(str(e), all_tools)
            if recovered:
                fn_name, fn_args, observation = recovered
                _t_hop = time.time()
                tool_observations.append(str(observation))
                _trace_logger.log_hop(
                    trace_id=_trace_id, hop_index=_hop_index, tool_name=fn_name,
                    tool_args=fn_args, observation=str(observation),
                    elapsed_ms=(time.time() - _t_hop) * 1000,
                )
                _hop_index += 1
                messages.append(HumanMessage(content=f"Résultat de l'outil {fn_name} : {observation}"))
                continue

            logger.error("Unrecoverable LLM error at iteration %d", iteration + 1)
            break

        messages.append(ai_msg)

        if not getattr(ai_msg, "tool_calls", None):
            final_answer = ai_msg.content
            logger.info("Node [orm_agent_loop]: Final answer at iteration %d", iteration + 1)
            break

        for tool_call in ai_msg.tool_calls:
            _t_hop = time.time()
            tool_name, tool_args, observation = execute_tool_call(tool_call, all_tools)
            tool_observations.append(observation)
            _trace_logger.log_hop(
                trace_id=_trace_id, hop_index=_hop_index, tool_name=tool_name,
                tool_args=tool_args, observation=str(observation),
                elapsed_ms=(time.time() - _t_hop) * 1000,
            )
            _hop_index += 1
            messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
    else:
        final_answer, extra_calls = force_final_synthesis(question, tool_observations)
        _llm_call_count += extra_calls

    if not final_answer:
        final_answer = "Je n'ai pas de données disponibles pour répondre à cette question."

    sources = [
        SourceReference(
            source="odoo://xmlrpc", doc_type="erp_data",
            title="Données ERP Odoo", snippet=str(obs)[:150],
        )
        for obs in tool_observations if obs and str(obs).strip()
    ]

    response = AssistantResponse(
        answer=final_answer, sources=sources,
        confidence=0.9 if tool_observations else 0.5,
    )

    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    timing["llm_call_count"] = _llm_call_count
    timing["hop_count"] = _hop_index
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="donnees_erp", question=question,
        hop_count=_hop_index, llm_call_count=_llm_call_count,
        total_time_ms=timing["generation_time"] * 1000,
        hop_cap=REACT_RECURSION_LIMIT,
    )
    return {
        "response": response,
        "raw_answer": response.answer,
        "timing": timing,
        "raw_tool_output": "\n\n".join(str(obs) for obs in tool_observations),
    }


def hybrid_node(state: RAGState) -> dict:
    """Agent that orchestrates a hybrid query by dispatching to doc and data agents sequentially."""
    start_time = time.time()
    logger.info("Node [hybrid_node]: Delegating to doc agent and data agent")

    doc_state = state.copy()
    doc_result = generate(doc_state)
    doc_answer = doc_result.get("raw_answer", "")

    data_state = state.copy()
    data_state["retrieved_chunks"] = []
    data_state["question"] = state["question"]
    data_result = orm_agent_loop(data_state)
    data_answer = data_result.get("raw_answer", "")

    from erp_data.prompts import build_hybrid_combine_prompt
    combine_prompt = build_hybrid_combine_prompt(state["question"], doc_answer, data_answer)

    try:
        _combine_llm_box = [_build_llm(temperature=0.3, max_retries=0, max_tokens=1024)]

        def _rebuild_combine_llm():
            _combine_llm_box[0] = _build_llm(temperature=0.3, max_retries=0, max_tokens=1024)
            return _combine_llm_box[0]

        final_resp, _ = _invoke_with_rate_limit(
            _combine_llm_box[0], [HumanMessage(content=combine_prompt)],
            rebuild_llm=_rebuild_combine_llm,
        )
        final_answer = final_resp.content
    except Exception as e:
        logger.error("Hybrid combine failed: %s", e)
        final_answer = f"{doc_answer}\n\n{data_answer}"

    sources = []
    if doc_result.get("response") and doc_result["response"].sources:
        sources.extend(doc_result["response"].sources)
    if data_result.get("response") and data_result["response"].sources:
        sources.extend(data_result["response"].sources)

    confidence = 0.5
    if doc_result.get("response") and data_result.get("response"):
        confidence = min(doc_result["response"].confidence, data_result["response"].confidence)

    response = AssistantResponse(answer=final_answer, sources=sources, confidence=confidence)
    timing = state.get("timing", {}).copy()
    timing["hybrid_time"] = time.time() - start_time
    return {"response": response, "raw_answer": final_answer, "timing": timing}
