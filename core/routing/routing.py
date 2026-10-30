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
    if source_mode in SOURCES:
        decision, confidence = source_mode, 1.0
    elif source_mode:
        decision, confidence = SOURCE_CLARIFICATION, 0.0
    else:
        selection = select_source(state.get('question', ''))
        confident = selection.confidence >= SOURCE_SELECTION_MIN_CONFIDENCE
        decision = selection.source if selection.source in SOURCES and confident else SOURCE_CLARIFICATION
        confidence = selection.confidence
    timing = dict(state.get('timing') or {})
    timing['routing_time'] = time.perf_counter() - started
    timing['source_selection_confidence'] = confidence
    result = {'route': decision, 'timing': timing}
    if decision not in SOURCES:
        result['response'] = AssistantResponse(
            answer='Would you like an answer based on the system or on the internal documents?',
            sources=[], confidence=0.0)
    logger.info('Source routing: route=%s confidence=%.2f', decision, confidence)
    return result


def route_decision(state: RAGState) -> str:
    return state.get('route') or SOURCE_CLARIFICATION
