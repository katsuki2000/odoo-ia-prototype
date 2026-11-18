"""Documentary RAG branch -- generates structured answers from retrieved document chunks."""

import logging
import time

from core.messages import GENERATION_ERROR_ANSWER, NO_SOURCE_ANSWER
from core.schemas import AssistantResponse, LLMResponse, QueryRoute
import config.settings as settings
from core.state import RAGState
from core.llm import get_chat_llm, invoke_llm
from core.session.reasoning_trace_logger import ReasoningTraceLogger, finish_branch, new_trace_id
from document_rag.generation.generate_helpers import (
    build_source_aliases as _build_source_aliases,
    cited_chunks,
    format_context as _format_context,
    has_low_quality_ocr,
    verify_used_sources as _verify_used_sources,
    compute_rag_confidence,
    parse_raw_json_answer as _parse_raw_json_answer,
    strip_source_aliases as _strip_source_aliases,
)

logger = logging.getLogger(__name__)

_build_llm = get_chat_llm


def _build_answer_llm():
    return _build_llm(temperature=0.3, max_tokens=settings.DOCUMENT_MAX_TOKENS,
                      reasoning_effort=settings.RAG_REASONING_EFFORT)


def generate(state: RAGState) -> dict:
    """Generate structured answer using configured LLM (documentary branch)."""
    start_time = time.time()
    question = state["question"]
    chunks = state["retrieved_chunks"]
    logger.info("Node [generate]: Building prompt and calling LLM")

    trace_logger, trace_id = ReasoningTraceLogger(), new_trace_id()

    if not chunks:
        logger.info("Node [generate]: No chunks retrieved, falling back.")
        response = AssistantResponse(
            answer=NO_SOURCE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = finish_branch(trace_logger, trace_id, QueryRoute.DOCUMENTARY.value, question, state, start_time, 0)
        return {"response": response, "timing": timing}

    from document_rag.generation.prompts import build_rag_messages as build_messages

    alias_map = _build_source_aliases(chunks)
    context_text = _format_context(alias_map)

    chat_history = state.get("chat_history", [])
    messages = build_messages(question, context_text, chat_history)

    _llm_call_count = 0
    structured_failed = False
    try:
        llm = _build_answer_llm()
        llm_resp = invoke_llm(llm.with_structured_output(LLMResponse, method='json_schema'), messages)
        _llm_call_count += 1
        response = AssistantResponse(
            answer=_strip_source_aliases(llm_resp.answer),
            confidence=llm_resp.confidence,
            sources=_verify_used_sources(llm_resp.used_sources, alias_map),
            ocr_warning=has_low_quality_ocr(cited_chunks(llm_resp.used_sources, alias_map) or chunks),
        )
    except Exception as e:
        logger.warning("Structured LLM Generation failed (%s) → falling back to raw invoke", e)
        try:
            raw_resp = invoke_llm(_build_answer_llm(), messages)
            _llm_call_count += 1
            parsed_answer = _parse_raw_json_answer(raw_resp.content)
            response = AssistantResponse(
                answer=_strip_source_aliases(parsed_answer if parsed_answer is not None else raw_resp.content),
                confidence=compute_rag_confidence(chunks),
                sources=[],
                ocr_warning=has_low_quality_ocr(chunks),
            )
            structured_failed = True
        except Exception as e2:
            logger.error("Raw LLM Generation also failed: %s", e2)
            response = AssistantResponse(
                answer=GENERATION_ERROR_ANSWER,
                sources=[],
                confidence=0.0,
            )

    timing = finish_branch(
        trace_logger, trace_id, QueryRoute.DOCUMENTARY.value, question, state, start_time, _llm_call_count)
    return {"response": response, "timing": timing, "structured_failed": structured_failed}
