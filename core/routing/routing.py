"""Choose an evidence corpus or ask the user when the source is uncertain."""

import logging
import time

from config.settings import SOURCE_SELECTION_MIN_CONFIDENCE
from core.schemas import AssistantResponse, QueryRoute
from core.state import RAGState
from core.routing.source_selection import select_source
from core.routing.routing_keywords import (
    ERP_TYPES, ROUTING_CONFLICT_PRIORITY, ERP_KEYWORDS, CODE_INTEL_KEYWORDS,
    QUANTITATIVE_TERMS, DOC_KEYWORDS, DATA_TERMS, DOC_ANCHORS, THRESHOLD_QUERY_TERMS,
    _fold_accents, _fold_keywords, ERP_KEYWORDS_FOLDED, CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS_FOLDED, DOC_KEYWORDS_FOLDED, DATA_TERMS_FOLDED,
    DOC_ANCHORS_FOLDED, THRESHOLD_QUERY_TERMS_FOLDED,
)

logger = logging.getLogger(__name__)
SOURCE_CLARIFICATION = 'source_clarification'


def route(state: RAGState) -> dict:
    started = time.perf_counter()
    sourceMode = state.get('source_mode')
    confidence = 1.0
    if sourceMode in {'documentation', 'systeme'}:
        selected = sourceMode
    elif sourceMode:
        selected, confidence = 'uncertain', 0.0
    else:
        selection = select_source(state.get('question', ''))
        selected, confidence = selection.source, selection.confidence
    decision = (QueryRoute.DOCUMENTAIRE.value if selected == 'documentation'
                else QueryRoute.CODE_INTELLIGENCE.value if selected == 'systeme'
                else SOURCE_CLARIFICATION)
    if sourceMode not in {'documentation', 'systeme'} and confidence < SOURCE_SELECTION_MIN_CONFIDENCE:
        decision = SOURCE_CLARIFICATION
    timing = dict(state.get('timing') or {})
    timing['routing_time'] = time.perf_counter() - started
    timing['source_selection_confidence'] = confidence
    result = {'route': decision, 'timing': timing,
              'resolved_concept': None, 'investigation_plan': None}
    if decision not in {QueryRoute.DOCUMENTAIRE.value, QueryRoute.CODE_INTELLIGENCE.value}:
        result['response'] = AssistantResponse(
            answer='Souhaitez-vous une réponse selon le système Odoo ou d’après les documents internes ?',
            sources=[], confidence=0.0)
    logger.info('Source routing: selected=%s confidence=%.2f route=%s', selected, confidence, decision)
    return result


def route_decision(state: RAGState) -> str:
    return state.get('route') or SOURCE_CLARIFICATION
