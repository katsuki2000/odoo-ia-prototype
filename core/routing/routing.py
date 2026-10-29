"""Choose an evidence corpus or ask the user when the source is uncertain."""

import logging
import time

from config.settings import SOURCE_SELECTION_MIN_CONFIDENCE
from core.schemas import AssistantResponse, QueryRoute
from core.state import RAGState
from core.routing.source_selection import select_source


logger = logging.getLogger(__name__)
SOURCE_CLARIFICATION = 'source_clarification'
SOURCES = {QueryRoute.DOCUMENTARY.value, QueryRoute.ERP_DATA.value}


def route(state: RAGState) -> dict:
    started = time.perf_counter()
    source_mode = state.get('source_mode')
    confidence = 1.0
    if source_mode in SOURCES:
        selected = source_mode
    elif source_mode:
        selected, confidence = 'uncertain', 0.0
    else:
        selection = select_source(state.get('question', ''))
        selected, confidence = selection.source, selection.confidence
    decision = selected if selected in SOURCES else SOURCE_CLARIFICATION
    if source_mode not in SOURCES and confidence < SOURCE_SELECTION_MIN_CONFIDENCE:
        decision = SOURCE_CLARIFICATION
    timing = dict(state.get('timing') or {})
    timing['routing_time'] = time.perf_counter() - started
    timing['source_selection_confidence'] = confidence
    result = {'route': decision, 'timing': timing}
    if decision not in SOURCES:
        result['response'] = AssistantResponse(
            answer='Would you like an answer based on the system or on the internal documents?',
            sources=[], confidence=0.0)
    logger.info('Source routing: selected=%s confidence=%.2f route=%s', selected, confidence, decision)
    return result


def route_decision(state: RAGState) -> str:
    return state.get('route') or SOURCE_CLARIFICATION
