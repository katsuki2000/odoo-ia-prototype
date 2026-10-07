"""Query classification, routing, and input guardrails."""

import logging
import time
from typing import Any, List, Optional, TypedDict, TYPE_CHECKING
from langchain_core.messages import BaseMessage

if TYPE_CHECKING:
    from code_intelligence.agent.matching import ResolvedConcept

from core.schemas import AssistantResponse, QueryRoute
from code_intelligence.agent.investigation_planner import (
    generate_investigation_plan,
    validate_plan_against_route,
)
from code_intelligence.agent.investigation_classifier import has_documentary_anchor
from code_intelligence.agent.investigation_llm import resolve_question_intent

# Re-exports for backward compatibility
from core.routing.routing_keywords import (
    ERP_TYPES,
    ROUTING_CONFLICT_PRIORITY,
    ERP_KEYWORDS,
    CODE_INTEL_KEYWORDS,
    QUANTITATIVE_TERMS,
    DOC_KEYWORDS,
    DATA_TERMS,
    DOC_ANCHORS,
    THRESHOLD_QUERY_TERMS,
    CONDITIONAL_AMOUNT_TERMS,
    _fold_accents,
    _fold_keywords,
    ERP_KEYWORDS_FOLDED,
    CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS_FOLDED,
    DOC_KEYWORDS_FOLDED,
    DATA_TERMS_FOLDED,
    DOC_ANCHORS_FOLDED,
    THRESHOLD_QUERY_TERMS_FOLDED,
    CONDITIONAL_AMOUNT_TERMS_FOLDED,
    OUT_OF_SCOPE_ANSWER,
    OUT_OF_SCOPE_TERMS,
    _ARITHMETIC_ONLY_RE,
    REACT_RECURSION_LIMIT,
)
from core.routing.routing_guards import (
    _MASSIVE_EXTRACTION_PATTERNS,
    _PROMPT_INJECTION_PATTERNS,
    _is_out_of_scope,
    _is_massive_extraction_request,
    _is_prompt_injection,
)

logger = logging.getLogger(__name__)

_VALID_ROUTES = {r.value for r in QueryRoute}


class RAGState(TypedDict):
    """Workflow state container for the LangGraph agent network."""
    question: str
    chat_history: List[BaseMessage]
    uid: Optional[int]
    skills: Optional[dict]
    timing: dict
    retrieved_chunks: List[dict]
    raw_answer: str
    route: Optional[str]
    response: Optional[AssistantResponse]
    user_groups: List[int | str]
    user_groups_complete: Optional[bool]
    resolved_concept: Optional[dict]
    last_route: Optional[str]
    last_resolved_concept: Optional[dict]
    resolved_concept_reused: bool
    evidence_status: Optional[str]
    investigation_plan: Optional[dict]
    sources_fallback_eligible: Optional[bool]
    ci_evidence_sufficiency: Optional[dict]
    raw_tool_output: Optional[str]
    source_mode: Optional[str]
    language: Optional[str]


def _sticky_route_or_default(state: RAGState, default: str) -> str:
    """Sticky session routing: reuse previous turn's branch if no keyword signal."""
    last_route = state.get("last_route")
    if last_route in _VALID_ROUTES:
        logger.info(
            "Node [route]: No keyword signal -- sticky-routing to previous branch (%s) instead of %s",
            last_route, default,
        )
        return last_route
    return default


def _sticky_concept_or_resolve(state: RAGState, resolved_concept_dict: dict) -> dict:
    """Sticky concept reuse: reuse previous turn's resolved concept if current resolution failed."""
    if resolved_concept_dict.get("is_resolved"):
        return resolved_concept_dict
    prev = state.get("last_resolved_concept")
    if isinstance(prev, dict) and prev.get("is_resolved") is True:
        logger.info("Node [route]: reusing previous resolved_concept.")
        return prev
    return resolved_concept_dict


def route(state: RAGState) -> dict:
    """Classify the query via intent-based routing and plan generation."""
    start_time = time.time()
    question_raw = state.get("question", "")
    question_folded = _fold_accents(question_raw.lower())
    logger.info("Node [route]: Classifying query type via intent resolution")

    source_mode = state.get("source_mode")
    if source_mode == "documentation":
        # User explicitly chose "d'apres la documentation": no resolver, no intent LLM,
        # the CI agent node is skipped and ci_evidence_decision() sends
        # the turn straight to RAG generate (graph topology unchanged).
        timing = state.get("timing", {}).copy()
        timing["routing_time"] = time.time() - start_time
        logger.info("Node [route]: source_mode=documentation -> documentaire (RAG direct)")
        return {
            "route": QueryRoute.DOCUMENTAIRE.value,
            "timing": timing,
            "resolved_concept": None,
            "resolved_concept_reused": False,
            "investigation_plan": None,
        }

    from code_intelligence.agent.resolver import resolve_business_term
    from code_intelligence.agent.investigation_schemas import INTENT_TO_ROUTE, QuestionIntent
    from code_intelligence.graph.loader import get_code_intelligence_graph
    request_language = state.get("language")
    G = get_code_intelligence_graph(
        translation_languages=[request_language] if request_language else None,
        request_language=request_language,
    )

    resolved_concept = resolve_business_term(
        question_raw,
        G,
        llm=None,
        language=request_language,
    )

    intent_resolution = resolve_question_intent(question_raw, resolved_concept, G)
    intent = intent_resolution.intent
    logger.info("Node [route]: intent=%s source=%s", intent.value, intent_resolution.source)

    has_doc_anchor = has_documentary_anchor(question_folded)
    derived_route = INTENT_TO_ROUTE.get(intent, QueryRoute.DOCUMENTAIRE.value)

    if intent == QuestionIntent.DOCUMENTARY_POLICY and not has_doc_anchor:
        route_decision = _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value)
        logger.info(
            "Node [route]: DOCUMENTARY_POLICY, no explicit anchor -> sticky/default (%s)",
            route_decision,
        )
    else:
        route_decision = derived_route

    if source_mode == "systeme" and route_decision == QueryRoute.DOCUMENTAIRE.value:
        # User explicitly chose "d'apres le systeme": the documentary route is excluded.
        if any(term in question_folded for term in DATA_TERMS_FOLDED):
            route_decision = QueryRoute.DONNEES_ERP.value
        else:
            route_decision = QueryRoute.CODE_INTELLIGENCE.value
        logger.info("Node [route]: source_mode=systeme -> documentaire remapped to %s", route_decision)

    if route_decision in (QueryRoute.DOCUMENTAIRE.value, QueryRoute.DONNEES_ERP.value):
        is_hybrid = (
            any(kw in question_folded for kw in DOC_KEYWORDS_FOLDED) or has_doc_anchor
        ) and any(term in question_folded for term in QUANTITATIVE_TERMS_FOLDED)
        if is_hybrid:
            logger.info("Node [route]: doc-anchor/keyword + quantitative term -> HYBRIDE layer")
            route_decision = QueryRoute.HYBRIDE.value

    timing = state.get("timing", {}).copy()
    timing["routing_time"] = time.time() - start_time

    from dataclasses import asdict as _asdict
    resolved_concept_dict = _asdict(resolved_concept)
    resolved_concept_dict = _sticky_concept_or_resolve(state, resolved_concept_dict)
    resolved_concept_reused = resolved_concept_dict is state.get("last_resolved_concept")

    investigation_plan = generate_investigation_plan(
        question=question_raw,
        resolved_concept=resolved_concept,
        G=G,
        user_groups=state.get("user_groups"),
        intent=intent,
    )
    investigation_plan = validate_plan_against_route(investigation_plan, route_decision)

    return {
        "route": route_decision,
        "timing": timing,
        "resolved_concept": resolved_concept_dict,
        "resolved_concept_reused": resolved_concept_reused,
        "investigation_plan": investigation_plan.to_display_dict(),
    }


def route_decision(state: RAGState) -> str:
    """Return the routing key for conditional edges."""
    return state.get("route", QueryRoute.DOCUMENTAIRE.value)
