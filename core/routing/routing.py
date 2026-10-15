"""Query classification and planning from a shared resolution decision."""

import logging
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.agent.matching import ResolvedConcept

from core.schemas import QueryRoute
from core.state import RAGState
from code_intelligence.agent.investigation_planner import validate_plan_against_route
from code_intelligence.agent.capability_planner import generate_investigation_plan
from code_intelligence.agent.investigation_llm import resolve_question_intent
from core.routing.routing_keywords import (
    ERP_TYPES, ROUTING_CONFLICT_PRIORITY, ERP_KEYWORDS, CODE_INTEL_KEYWORDS,
    QUANTITATIVE_TERMS, DOC_KEYWORDS, DATA_TERMS, DOC_ANCHORS, THRESHOLD_QUERY_TERMS,
    _fold_accents, _fold_keywords, ERP_KEYWORDS_FOLDED, CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS_FOLDED, DOC_KEYWORDS_FOLDED, DATA_TERMS_FOLDED,
    DOC_ANCHORS_FOLDED, THRESHOLD_QUERY_TERMS_FOLDED,
)

logger = logging.getLogger(__name__)


def _sticky_concept_or_resolve(state: RAGState, resolved_concept_dict: dict) -> dict:
    """Do not replace a current abstention with a previous subject."""
    return resolved_concept_dict


def route(state: RAGState) -> dict:
    """Choose the source first, then resolve the business concept once for system questions."""
    started = time.time()
    question = state.get('question', '')
    folded = _fold_accents(question.lower())
    sourceMode = state.get('source_mode')
    timing = state.get('timing', {}).copy()
    if sourceMode == 'documentation':
        timing['routing_time'] = time.time() - started
        return {'route': QueryRoute.DOCUMENTAIRE.value, 'timing': timing,
                'resolved_concept': None, 'resolved_concept_reused': False, 'investigation_plan': None}
    from code_intelligence.agent.resolution.turn import resolve_turn
    from code_intelligence.agent.investigation_schemas import INTENT_TO_ROUTE
    from code_intelligence.graph.loader import get_code_intelligence_graph
    language = state.get('language')
    graph = get_code_intelligence_graph(translation_languages=[language] if language else None, request_language=language)
    concept, _cached = resolve_turn(question, graph, state, language=language)
    intentResolution = resolve_question_intent(question, concept, graph)
    intent = intentResolution.intent
    decision = INTENT_TO_ROUTE.get(intent, QueryRoute.DOCUMENTAIRE.value)
    if sourceMode == 'systeme' and decision == QueryRoute.DOCUMENTAIRE.value:
        decision = QueryRoute.DONNEES_ERP.value if any(term in folded for term in DATA_TERMS_FOLDED) else QueryRoute.CODE_INTELLIGENCE.value
    timing['routing_time'] = time.time() - started
    logger.info('Node [route]: route=%s intent=%s classifier=%s', decision, intent.value, intentResolution.source)
    if decision == QueryRoute.DOCUMENTAIRE.value:
        return {'route': decision, 'timing': timing, 'resolved_concept': None,
                'resolved_concept_reused': False, 'investigation_plan': None}
    plan = generate_investigation_plan(question=question, resolved_concept=concept, G=graph,
                                       user_groups=state.get('user_groups'), intent=intent)
    plan = validate_plan_against_route(plan, decision)
    return {'route': decision, 'timing': timing, 'resolved_concept': asdict(concept),
            'resolved_concept_reused': False, 'investigation_plan': plan.to_display_dict()}


def route_decision(state: RAGState) -> str:
    return state.get('route', QueryRoute.DOCUMENTAIRE.value)
