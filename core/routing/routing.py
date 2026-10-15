"""Query classification, routing, and input guardrails."""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.agent.matching import ResolvedConcept

from core.schemas import QueryRoute
from core.state import RAGState
from code_intelligence.agent.investigation_planner import (
    generate_investigation_plan,
    validate_plan_against_route,
)
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
    _fold_accents,
    _fold_keywords,
    ERP_KEYWORDS_FOLDED,
    CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS_FOLDED,
    DOC_KEYWORDS_FOLDED,
    DATA_TERMS_FOLDED,
    DOC_ANCHORS_FOLDED,
    THRESHOLD_QUERY_TERMS_FOLDED,
)

logger = logging.getLogger(__name__)


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
    """Choose the source first, then prepare system investigation only when needed."""
    start_time = time.time()
    question = state.get("question", "")
    source_mode = state.get("source_mode")

    timing = state.get("timing", {}).copy()

    # An explicit documentation choice bypasses all system/model resolution.
    if source_mode == "documentation":
        timing["routing_time"] = time.time() - start_time
        logger.info("Node [route]: explicit documentation source")
        return {
            "route": QueryRoute.DOCUMENTAIRE.value,
            "timing": timing,
            "resolved_concept": None,
            "resolved_concept_reused": False,
            "investigation_plan": None,
        }

    # Otherwise the LLM classifies the question. If it is unavailable, the
    # intent resolver uses its deterministic classifier as a fallback.
    from code_intelligence.agent.investigation_schemas import INTENT_TO_ROUTE
    intent_resolution = resolve_question_intent(question)
    intent = intent_resolution.intent
    route_decision = INTENT_TO_ROUTE.get(intent, QueryRoute.DOCUMENTAIRE.value)

    # An explicit system choice overrides a documentary classification.
    if source_mode == "systeme" and route_decision == QueryRoute.DOCUMENTAIRE.value:
        from core.routing.routing_keywords import DATA_TERMS_FOLDED
        folded_question = _fold_accents(question.lower())
        route_decision = (
            QueryRoute.DONNEES_ERP.value
            if any(term in folded_question for term in DATA_TERMS_FOLDED)
            else QueryRoute.CODE_INTELLIGENCE.value
        )

    timing["routing_time"] = time.time() - start_time
    logger.info(
        "Node [route]: route=%s intent=%s classifier=%s",
        route_decision, intent.value, intent_resolution.source,
    )

    # Documentation has its own retrieval/generation path; do not build or
    # resolve against the Odoo code graph for a documentation-only question.
    if route_decision == QueryRoute.DOCUMENTAIRE.value:
        return {
            "route": route_decision,
            "timing": timing,
            "resolved_concept": None,
            "resolved_concept_reused": False,
            "investigation_plan": None,
        }

    from code_intelligence.agent.resolver import resolve_business_term
    from code_intelligence.graph.loader import get_code_intelligence_graph

    request_language = state.get("language")
    G = get_code_intelligence_graph(
        translation_languages=[request_language] if request_language else None,
        request_language=request_language,
    )
    resolved_concept = resolve_business_term(
        question,
        G,
        llm=None,
        language=request_language,
    )

    from dataclasses import asdict
    resolved_concept_dict = _sticky_concept_or_resolve(
        state, asdict(resolved_concept)
    )
    resolved_concept_reused = (
        resolved_concept_dict is state.get("last_resolved_concept")
    )

    investigation_plan = generate_investigation_plan(
        question=question,
        resolved_concept=resolved_concept,
        G=G,
        user_groups=state.get("user_groups"),
        intent=intent,
    )
    investigation_plan = validate_plan_against_route(
        investigation_plan, route_decision
    )

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
