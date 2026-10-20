"""Choose documentation or the single system investigation agent."""

import logging
import time

from core.schemas import QueryRoute
from core.state import RAGState
# Historical imports used by graph_compat; not consulted by source routing.
from core.routing.routing_keywords import (
    ERP_TYPES, ROUTING_CONFLICT_PRIORITY, ERP_KEYWORDS, CODE_INTEL_KEYWORDS,
    QUANTITATIVE_TERMS, DOC_KEYWORDS, DATA_TERMS, DOC_ANCHORS, THRESHOLD_QUERY_TERMS,
    _fold_accents, _fold_keywords, ERP_KEYWORDS_FOLDED, CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS_FOLDED, DOC_KEYWORDS_FOLDED, DATA_TERMS_FOLDED,
    DOC_ANCHORS_FOLDED, THRESHOLD_QUERY_TERMS_FOLDED,
)

logger = logging.getLogger(__name__)


def route(state: RAGState) -> dict:
    started = time.perf_counter()
    sourceMode = state.get('source_mode')
    if sourceMode == 'documentation':
        decision = QueryRoute.DOCUMENTAIRE.value
    elif sourceMode == 'systeme':
        decision = QueryRoute.CODE_INTELLIGENCE.value
    else:
        from code_intelligence.agent.investigation_llm import resolve_question_intent
        from code_intelligence.agent.investigation_schemas import QuestionIntent
        resolution = resolve_question_intent(state.get('question', ''))
        decision = (QueryRoute.DOCUMENTAIRE.value
                    if resolution.intent == QuestionIntent.DOCUMENTARY_POLICY
                    else QueryRoute.CODE_INTELLIGENCE.value)
    timing = dict(state.get('timing') or {})
    timing['routing_time'] = time.perf_counter() - started
    logger.info('Node [route]: source=%s route=%s', sourceMode, decision)
    return {'route': decision, 'timing': timing,
            'resolved_concept': None, 'investigation_plan': None}


def route_decision(state: RAGState) -> str:
    return state.get('route', QueryRoute.DOCUMENTAIRE.value)
