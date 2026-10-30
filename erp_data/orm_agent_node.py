"""ORM ReAct agent loop (ERP data queries)."""

import logging
import time
from typing import Any, List, NamedTuple, Optional

from langchain_core.messages import ToolMessage

from config.settings import ORM_CONFIDENCE_WITH_DATA, ORM_CONFIDENCE_WITHOUT_DATA, REACT_RECURSION_LIMIT
from core.guardrails import PROMPT_INJECTION_REFUSAL_MSG, is_prompt_injection
from core.llm.llm_client import invoke_llm
from core.schemas import AssistantResponse, QueryRoute, SourceReference
from core.session.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
from core.state import RAGState
from erp_data.orm_agent_helpers import (
    _build_llm,
    execute_tool_call,
    force_final_synthesis,
    resolve_orm_tools,
)
from erp_data.prompts import build_orm_agent_messages

logger = logging.getLogger(__name__)

NO_DATA_ANSWER = "I have no data available to answer this question."


class ReactResult(NamedTuple):
    answer: Optional[str]
    observations: List[Any]
    llm_calls: int
    hops: int


def _run_react(question: str, chat_history: list, trace_logger: ReasoningTraceLogger, trace_id: str) -> ReactResult:
    """Reason, call an ORM tool, observe, repeat until an answer or the iteration budget is spent."""
    tools = resolve_orm_tools()
    tool_llm = _build_llm(temperature=0.0).bind_tools(tools)
    messages = build_orm_agent_messages(question, chat_history)
    observations: List[Any] = []
    llm_calls = hops = 0

    for iteration in range(REACT_RECURSION_LIMIT):
        logger.info("Node [orm_agent_loop]: Iteration %d/%d", iteration + 1, REACT_RECURSION_LIMIT)
        llm_calls += 1
        try:
            ai_msg = invoke_llm(tool_llm, messages)
        except Exception as error:
            logger.error("LLM invoke failed at iteration %d: %s", iteration + 1, error)
            return ReactResult(None, observations, llm_calls, hops)
        messages.append(ai_msg)

        if not getattr(ai_msg, "tool_calls", None):
            return ReactResult(ai_msg.content, observations, llm_calls, hops)

        for tool_call in ai_msg.tool_calls:
            started = time.time()
            tool_name, tool_args, observation = execute_tool_call(tool_call, tools)
            observations.append(observation)
            trace_logger.log_hop(
                trace_id=trace_id, hop_index=hops, tool_name=tool_name, tool_args=tool_args,
                observation=str(observation), elapsed_ms=(time.time() - started) * 1000,
            )
            hops += 1
            messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))

    answer, extra_calls = force_final_synthesis(question, observations)
    return ReactResult(answer, observations, llm_calls + extra_calls, hops)


def _build_response(result: ReactResult) -> AssistantResponse:
    sources = [
        SourceReference(source="odoo://xmlrpc", doc_type="erp_data", title="Odoo ERP data", snippet=str(obs)[:150])
        for obs in result.observations if obs and str(obs).strip()
    ]
    confidence = ORM_CONFIDENCE_WITH_DATA if result.observations else ORM_CONFIDENCE_WITHOUT_DATA
    return AssistantResponse(answer=result.answer or NO_DATA_ANSWER, sources=sources, confidence=confidence)


def orm_agent_loop(state: RAGState) -> dict:
    """ERP data branch: answer a question by reading Odoo through the typed ORM tools."""
    start_time = time.time()
    question = state["question"]
    logger.info("Node [orm_agent_loop]: Starting ReAct loop for: %s", question)

    trace_logger = ReasoningTraceLogger()
    trace_id = new_trace_id()
    if is_prompt_injection(question):
        logger.info("Node [orm_agent_loop]: Prompt injection refused, no LLM call.")
        result = ReactResult(PROMPT_INJECTION_REFUSAL_MSG, [], 0, 0)
        response = AssistantResponse(answer=PROMPT_INJECTION_REFUSAL_MSG, sources=[], confidence=0.0)
    else:
        result = _run_react(question, state.get("chat_history", []), trace_logger, trace_id)
        response = _build_response(result)

    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    timing["llm_call_count"] = result.llm_calls
    timing["hop_count"] = result.hops
    trace_logger.log_summary(
        trace_id=trace_id, branch=QueryRoute.ERP_DATA.value, question=question,
        hop_count=result.hops, llm_call_count=result.llm_calls,
        total_time_ms=timing["generation_time"] * 1000, hop_cap=REACT_RECURSION_LIMIT,
    )
    return {
        "response": response,
        "timing": timing,
        "raw_tool_output": "\n\n".join(str(obs) for obs in result.observations),
    }
