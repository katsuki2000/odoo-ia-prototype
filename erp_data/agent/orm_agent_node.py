"""ORM ReAct agent loop (ERP data queries)."""

import logging
import time
from typing import Any, List, NamedTuple, Optional

from langchain_core.messages import HumanMessage, ToolMessage

from config.settings import (
    ORM_CONFIDENCE_WITH_DATA,
    ORM_CONFIDENCE_WITHOUT_DATA,
    ORM_EMPTY_REPLY_RETRY_TEMPERATURE,
    ORM_MAX_EMPTY_REPLIES,
    ORM_MAX_QUERY_REFUSALS,
    REACT_RECURSION_LIMIT,
)
from core.evidence import filter_disclosed_evidence, peek_turn_evidence
from core.llm import invoke_llm
from core.messages import LLM_UNAVAILABLE_ANSWER, NO_DATA_ANSWER, NO_READ_ANSWER
from core.schemas import AssistantResponse, QueryRoute, SourceReference
from core.session.reasoning_trace_logger import ReasoningTraceLogger, finish_branch, new_trace_id
from core.state import RAGState
from erp_data.agent.orm_agent_helpers import (
    DOMAIN_QUERY_TOOLS,
    QueryPlan,
    _build_llm,
    answered_without_reading,
    counted_instead_of_listed,
    counted_instead_of_measured,
    execute_tool_call,
    explain_refusals,
    force_final_synthesis,
    format_query_plan,
    is_query_contract_refusal,
    plan_orm_question,
    resolve_orm_tools,
    successful_tool_observation,
)
from erp_data.agent.prompts import (
    EMPTY_REPLY_REMINDER,
    LIST_READ_REMINDER,
    MEASURE_READ_REMINDER,
    NO_READ_REMINDER,
    build_orm_agent_messages,
    build_read_reminder_message,
)
from erp_data.tools.read_tools import SCHEMA_METHODS, active_company_name

logger = logging.getLogger(__name__)



def _missing_read_reminder(plan: QueryPlan | None, tool_names: List[str]) -> Optional[str]:
    if counted_instead_of_measured(plan, tool_names):
        return MEASURE_READ_REMINDER
    if counted_instead_of_listed(plan, tool_names):
        return LIST_READ_REMINDER
    if answered_without_reading(plan, tool_names):
        return NO_READ_REMINDER
    return None


class ReactResult(NamedTuple):
    answer: Optional[str]
    observations: List[Any]
    llm_calls: int
    hops: int
    llm_unavailable: bool = False


def _run_react(
    question: str,
    chat_history: list,
    trace_logger: ReasoningTraceLogger,
    trace_id: str,
    plan: QueryPlan | None = None,
    planning_calls: int = 0,
) -> ReactResult:
    """Reason, call an ORM tool, observe, repeat until an answer or the iteration budget is spent."""
    tools = resolve_orm_tools()
    tool_llm = _build_llm(temperature=0.0).bind_tools(tools)
    retry_llm = None
    messages = build_orm_agent_messages(
        question, chat_history, query_plan=plan and format_query_plan(plan), company_name=active_company_name()
    )
    observations: List[Any] = []
    tool_names: List[str] = []
    reminded: set[str] = set()
    query_refusals = 0
    contract_refusals = 0
    empty_reply = False
    empty_replies = 0
    llm_calls, hops = planning_calls, 0

    for iteration in range(REACT_RECURSION_LIMIT):
        logger.info("Node [orm_agent_loop]: Iteration %d/%d", iteration + 1, REACT_RECURSION_LIMIT)
        llm_calls += 1
        llm = tool_llm
        if empty_reply:
            retry_llm = retry_llm or _build_llm(temperature=ORM_EMPTY_REPLY_RETRY_TEMPERATURE).bind_tools(tools)
            llm = retry_llm
        try:
            ai_msg = invoke_llm(llm, messages)
        except Exception as error:
            logger.error("LLM invoke failed at iteration %d: %s", iteration + 1, error)
            return ReactResult(None, observations, llm_calls, hops, llm_unavailable=True)
        messages.append(ai_msg)

        if not getattr(ai_msg, "tool_calls", None):
            reminder = _missing_read_reminder(plan, tool_names)
            if reminder and reminder not in reminded:
                reminded.add(reminder)
                messages.append(HumanMessage(content=build_read_reminder_message(question, reminder)))
                continue
            if str(ai_msg.content).strip():
                return ReactResult(ai_msg.content, observations, llm_calls, hops)
            empty_replies += 1
            logger.warning(
                "Node [orm_agent_loop]: empty reply %d/%d, raw message: %.800r",
                empty_replies, ORM_MAX_EMPTY_REPLIES, ai_msg,
            )
            if empty_replies >= ORM_MAX_EMPTY_REPLIES:
                break
            messages.append(HumanMessage(content=EMPTY_REPLY_REMINDER))
            empty_reply = True
            continue

        empty_reply = False
        empty_replies = 0
        for tool_call in ai_msg.tool_calls:
            started = time.time()
            tool_name, tool_args, observation, covers_plan = execute_tool_call(tool_call, tools, plan)
            observation_succeeded = successful_tool_observation(observation)
            if tool_name in DOMAIN_QUERY_TOOLS and observation_succeeded:
                logger.info("Node [orm_agent_loop]: %s domain covers the plan: %s", tool_name, covers_plan)
            observations.append(observation)
            tool_names.append(tool_name)
            trace_logger.log_hop(
                trace_id=trace_id, hop_index=hops, tool_name=tool_name, tool_args=tool_args,
                observation=str(observation), elapsed_ms=(time.time() - started) * 1000,
            )
            hops += 1
            messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
            if not observation_succeeded:
                if is_query_contract_refusal(observation):
                    contract_refusals += 1
                    if contract_refusals >= ORM_MAX_QUERY_REFUSALS:
                        return ReactResult(None, observations, llm_calls, hops)
                else:
                    query_refusals += 1
                    if query_refusals >= ORM_MAX_QUERY_REFUSALS:
                        return ReactResult(None, observations, llm_calls, hops)

    answer, extra_calls = force_final_synthesis(question, observations)
    return ReactResult(answer, observations, llm_calls + extra_calls, hops)


def _build_response(question: str, result: ReactResult) -> tuple[AssistantResponse, int]:
    """Response and extra LLM calls. Sources and confidence rest on this turn's successful data reads: refused
    calls and schema reads (model list, field list) are not data. Without a data read and after a failed tool call,
    the model's answer is replaced by an explanation of the failure; without a failure it is kept. When the model
    itself could not be reached, a fixed message says so: it is neither an absence of data nor a refusal."""
    if result.llm_unavailable:
        return AssistantResponse(answer=LLM_UNAVAILABLE_ANSWER, sources=[], confidence=ORM_CONFIDENCE_WITHOUT_DATA), 0
    reads = [item for item in peek_turn_evidence() if item.scope.get("method") not in SCHEMA_METHODS]
    if not reads and any(not successful_tool_observation(item) for item in result.observations):
        explanation, extra_calls = explain_refusals(question, [str(item) for item in result.observations])
        answer = explanation or NO_READ_ANSWER
        return AssistantResponse(answer=answer, sources=[], confidence=ORM_CONFIDENCE_WITHOUT_DATA), extra_calls
    sources = [
        SourceReference(source="odoo://xmlrpc", doc_type="erp_data", title="Odoo ERP data", snippet=item.claim)
        for item in filter_disclosed_evidence(reads)
    ]
    confidence = ORM_CONFIDENCE_WITH_DATA if reads else ORM_CONFIDENCE_WITHOUT_DATA
    return AssistantResponse(answer=result.answer or NO_DATA_ANSWER, sources=sources, confidence=confidence), 0


def orm_agent_loop(state: RAGState) -> dict:
    """ERP data branch: answer a question by reading Odoo through the typed ORM tools."""
    start_time = time.time()
    question = state["question"]
    logger.info("Node [orm_agent_loop]: Starting ReAct loop for: %s", question)

    trace_logger = ReasoningTraceLogger()
    trace_id = new_trace_id()
    query_plan, planning_calls = plan_orm_question(question, _build_llm)
    result = _run_react(
        question, state.get("chat_history", []), trace_logger, trace_id,
        plan=query_plan, planning_calls=planning_calls,
    )
    response, extra_calls = _build_response(question, result)

    timing = finish_branch(
        trace_logger, trace_id, QueryRoute.ERP_DATA.value, question, state, start_time,
        result.llm_calls + extra_calls, hops=result.hops, hop_cap=REACT_RECURSION_LIMIT,
    )
    return {
        "response": response,
        "timing": timing,
        "raw_tool_output": "\n\n".join(str(obs) for obs in result.observations),
    }
