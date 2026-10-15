"""Query classification and planning from a shared resolution decision."""

import logging
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.agent.matching import ResolvedConcept

from core.schemas import QueryRoute
from core.state import RAGState
from code_intelligence.agent.investigation_planner import generate_investigation_plan, validate_plan_against_route
from code_intelligence.agent.investigation_classifier import has_documentary_anchor
from code_intelligence.agent.investigation_llm import resolve_question_intent
from core.routing.routing_keywords import (
    ERP_TYPES, ROUTING_CONFLICT_PRIORITY, ERP_KEYWORDS, CODE_INTEL_KEYWORDS,
    QUANTITATIVE_TERMS, DOC_KEYWORDS, DATA_TERMS, DOC_ANCHORS, THRESHOLD_QUERY_TERMS,
    _fold_accents, _fold_keywords, ERP_KEYWORDS_FOLDED, CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS_FOLDED, DOC_KEYWORDS_FOLDED, DATA_TERMS_FOLDED,
    DOC_ANCHORS_FOLDED, THRESHOLD_QUERY_TERMS_FOLDED,
)

logger = logging.getLogger(__name__)
_VALID_ROUTES = {route.value for route in QueryRoute}


def _sticky_route_or_default(state: RAGState, default: str) -> str:
    previous = state.get('last_route')
    return previous if previous in _VALID_ROUTES else default


def _sticky_concept_or_resolve(state: RAGState, resolved_concept_dict: dict) -> dict:
    """Do not replace a current abstention with a previous subject."""
    return resolved_concept_dict


def route(state: RAGState) -> dict:
    started = time.time()
    question = state.get('question', '')
    folded = _fold_accents(question.lower())
    sourceMode = state.get('source_mode')
    if sourceMode == 'documentation':
        timing = state.get('timing', {}).copy()
        timing['routing_time'] = time.time() - started
        return {'route': QueryRoute.DOCUMENTAIRE.value, 'timing': timing,
                'resolved_concept': None, 'resolved_concept_reused': False, 'investigation_plan': None}
    from code_intelligence.agent.resolution.turn import resolve_turn
    from code_intelligence.agent.investigation_schemas import INTENT_TO_ROUTE, QuestionIntent
    from code_intelligence.graph.loader import get_code_intelligence_graph
    language = state.get('language')
    graph = get_code_intelligence_graph(translation_languages=[language] if language else None, request_language=language)
    concept, _cached = resolve_turn(question, graph, state, language=language)
    intentResolution = resolve_question_intent(question, concept, graph)
    intent = intentResolution.intent
    hasAnchor = has_documentary_anchor(folded)
    decision = INTENT_TO_ROUTE.get(intent, QueryRoute.DOCUMENTAIRE.value)
    if intent == QuestionIntent.DOCUMENTARY_POLICY and not hasAnchor:
        decision = _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value)
    if sourceMode == 'systeme' and decision == QueryRoute.DOCUMENTAIRE.value:
        decision = QueryRoute.DONNEES_ERP.value if any(term in folded for term in DATA_TERMS_FOLDED) else QueryRoute.CODE_INTELLIGENCE.value
    if decision in (QueryRoute.DOCUMENTAIRE.value, QueryRoute.DONNEES_ERP.value):
        if (hasAnchor or any(term in folded for term in DOC_KEYWORDS_FOLDED)) and any(term in folded for term in QUANTITATIVE_TERMS_FOLDED):
            decision = QueryRoute.HYBRIDE.value
    plan = generate_investigation_plan(question=question, resolved_concept=concept, G=graph,
                                       user_groups=state.get('user_groups'), intent=intent)
    plan = validate_plan_against_route(plan, decision)
    timing = state.get('timing', {}).copy()
    timing['routing_time'] = time.time() - started
    return {'route': decision, 'timing': timing, 'resolved_concept': asdict(concept),
            'resolved_concept_reused': False, 'investigation_plan': plan.to_display_dict()}


def route_decision(state: RAGState) -> str:
    return state.get('route', QueryRoute.DOCUMENTAIRE.value)
