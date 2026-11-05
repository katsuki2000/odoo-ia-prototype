"""ORM ReAct agent loop (ERP data queries)."""

import logging
import time
from typing import Any, List, NamedTuple, Optional

from langchain_core.messages import HumanMessage, ToolMessage

from config.settings import (
    ORM_CONFIDENCE_WITH_DATA,
    ORM_CONFIDENCE_WITHOUT_DATA,
    ORM_MAX_QUERY_REFUSALS,
    REACT_RECURSION_LIMIT,
)
from core.evidence.disclosure import filter_disclosed_evidence
from core.evidence.evidence_collector import peek_turn_evidence
from core.guardrails import PROMPT_INJECTION_REFUSAL_MSG, is_prompt_injection
from core.llm.llm_client import invoke_llm
from core.schemas import AssistantResponse, QueryRoute, SourceReference
from core.session.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
from core.state import RAGState
from erp_data.orm_agent_helpers import (
    DOMAIN_QUERY_TOOLS,
    QueryPlan,
    _build_llm,
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
from erp_data.prompts import EMPTY_REPLY_REMINDER, MEASURE_READ_REMINDER, build_orm_agent_messages
from erp_data.runtime.read_tools import SCHEMA_METHODS

logger = logging.getLogger(__name__)

NO_DATA_ANSWER = "Je n'ai pas de données disponibles pour répondre à cette question."
NO_READ_ANSWER = (
    "Je n'ai pas pu lire les données nécessaires pour répondre : les accès ont été refusés ou ont échoué. "
    "Précisez le sujet, le statut ou la période, ou reformulez la question."
)
INCOMPLETE_QUERY_ANSWER = (
    "Je ne peux pas confirmer le résultat : toutes les conditions obligatoires de la question "
    "n'ont pas été appliquées à une lecture réussie des données."
)
CONDITION_COVERAGE_REMINDER = (
    "La requête exécutée ne couvre pas encore toutes les conditions obligatoires du plan. "
    "En t'appuyant sur fields_get, exécute une lecture dont le domaine applique chaque condition avant de "
    "répondre. Si une correspondance n'est pas démontrable, demande une précision au lieu de conclure à "
    "partir du résultat partiel."
)


class ReactResult(NamedTuple):
    answer: Optional[str]
    observations: List[Any]
    llm_calls: int
    hops: int
    conditions_covered: bool = True


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
    messages = build_orm_agent_messages(question, chat_history, query_plan=plan and format_query_plan(plan))
    observations: List[Any] = []
    tool_names: List[str] = []
    measure_reminded = False
    conditions_covered = plan is None or not plan.conditions
    coverage_reminded = False
    query_refusals = 0
    contract_refusals = 0
    llm_calls, hops = planning_calls, 0

    for iteration in range(REACT_RECURSION_LIMIT):
        logger.info("Node [orm_agent_loop]: Iteration %d/%d", iteration + 1, REACT_RECURSION_LIMIT)
        llm_calls += 1
        try:
            ai_msg = invoke_llm(tool_llm, messages)
        except Exception as error:
            logger.error("LLM invoke failed at iteration %d: %s", iteration + 1, error)
            return ReactResult(None, observations, llm_calls, hops, conditions_covered)
        messages.append(ai_msg)

        if not getattr(ai_msg, "tool_calls", None):
            if not conditions_covered:
                if coverage_reminded:
                    return ReactResult(None, observations, llm_calls, hops, False)
                messages.append(HumanMessage(content=CONDITION_COVERAGE_REMINDER))
                coverage_reminded = True
                continue
            if counted_instead_of_measured(plan, tool_names) and not measure_reminded:
                measure_reminded = True
                messages.append(HumanMessage(content=MEASURE_READ_REMINDER))
                continue
            if str(ai_msg.content).strip():
                return ReactResult(ai_msg.content, observations, llm_calls, hops)
            messages.append(HumanMessage(content=EMPTY_REPLY_REMINDER))
            continue

        for tool_call in ai_msg.tool_calls:
            started = time.time()
            tool_name, tool_args, observation, coverage_complete = execute_tool_call(tool_call, tools, plan)
            observation_succeeded = successful_tool_observation(observation)
            if tool_name in DOMAIN_QUERY_TOOLS and observation_succeeded:
                conditions_covered = coverage_complete or plan is None or not plan.conditions
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
                        return ReactResult(None, observations, llm_calls, hops, False)
                else:
                    query_refusals += 1
                    if query_refusals >= ORM_MAX_QUERY_REFUSALS:
                        return ReactResult(None, observations, llm_calls, hops, False)

    if not conditions_covered:
        return ReactResult(None, observations, llm_calls, hops, False)
    answer, extra_calls = force_final_synthesis(question, observations)
    return ReactResult(answer, observations, llm_calls + extra_calls, hops)


def _build_response(question: str, result: ReactResult) -> tuple[AssistantResponse, int]:
    """Response and extra LLM calls. Sources and confidence rest on this turn's successful data reads: refused
    calls and schema reads (model list, field list) are not data, so without one the model's answer is replaced
    by an explanation of why nothing could be read."""
    if not result.conditions_covered:
        return AssistantResponse(
            answer=INCOMPLETE_QUERY_ANSWER, sources=[], confidence=0.0,
        ), 0
    reads = [item for item in peek_turn_evidence() if item.scope.get("method") not in SCHEMA_METHODS]
    if result.observations and not reads:
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
    if is_prompt_injection(question):
        logger.info("Node [orm_agent_loop]: Prompt injection refused, no LLM call.")
        result = ReactResult(PROMPT_INJECTION_REFUSAL_MSG, [], 0, 0)
        response, extra_calls = AssistantResponse(answer=PROMPT_INJECTION_REFUSAL_MSG, sources=[], confidence=0.0), 0
    else:
        query_plan, planning_calls = plan_orm_question(question, _build_llm)
        result = _run_react(
            question, state.get("chat_history", []), trace_logger, trace_id,
            plan=query_plan, planning_calls=planning_calls,
        )
        response, extra_calls = _build_response(question, result)

    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    timing["llm_call_count"] = result.llm_calls + extra_calls
    timing["hop_count"] = result.hops
    trace_logger.log_summary(
        trace_id=trace_id, branch=QueryRoute.ERP_DATA.value, question=question,
        hop_count=result.hops, llm_call_count=timing["llm_call_count"],
        total_time_ms=timing["generation_time"] * 1000, hop_cap=REACT_RECURSION_LIMIT,
    )
    return {
        "response": response,
        "timing": timing,
        "raw_tool_output": "\n\n".join(str(obs) for obs in result.observations),
    }
