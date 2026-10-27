"""Documentary RAG branch -- generates structured answers from retrieved document chunks."""

import logging
import time

from core.schemas import AssistantResponse, LLMResponse
from config.settings import DOCUMENT_MAX_TOKENS
from core.guardrails import OUT_OF_SCOPE_ANSWER, is_out_of_scope
from core.state import RAGState
from core.llm.llm_client import (
    get_chat_llm,
    invoke_with_rate_limit as _invoke_with_rate_limit,
)
from document_rag.generate_helpers import (
    build_source_aliases as _build_source_aliases,
    format_context as _format_context,
    verify_used_sources as _verify_used_sources,
    compute_rag_confidence,
    parse_raw_json_answer as _parse_raw_json_answer,
    strip_source_aliases as _strip_source_aliases,
)

logger = logging.getLogger(__name__)

_build_llm = get_chat_llm



def generate(state: RAGState) -> dict:
    """Generate structured answer using configured LLM (documentary branch)."""
    start_time = time.time()
    question = state["question"]
    chunks = state["retrieved_chunks"]
    logger.info("Node [generate]: Building prompt and calling LLM")

    from core.session.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
    _trace_id = new_trace_id()
    _trace_logger = ReasoningTraceLogger()

    if is_out_of_scope(question):
        logger.info("Node [generate]: Deterministic out-of-scope refusal.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="documentaire", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    if not chunks:
        logger.info("Node [generate]: No chunks retrieved, falling back.")
        response = AssistantResponse(
            answer="Je n'ai pas de source fiable pour répondre à cette question.",
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="documentaire", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    from document_rag.prompts import build_rag_messages as build_messages

    alias_map = _build_source_aliases(chunks)
    context_text = _format_context(alias_map)

    chat_history = state.get("chat_history", [])
    messages = build_messages(question, context_text, chat_history)

    _llm_call_count = 0
    sources_fallback_eligible = False
    try:
        llm = _build_llm(temperature=0.3, max_retries=0, max_tokens=DOCUMENT_MAX_TOKENS)
        _structured_llm_box = [llm.with_structured_output(LLMResponse)]

        def _rebuild_structured_llm():
            fresh = _build_llm(temperature=0.3, max_retries=0, max_tokens=DOCUMENT_MAX_TOKENS)
            _structured_llm_box[0] = fresh.with_structured_output(LLMResponse)
            return _structured_llm_box[0]

        llm_resp, _wait = _invoke_with_rate_limit(
            _structured_llm_box[0], messages, rebuild_llm=_rebuild_structured_llm,
        )
        _llm_call_count += 1
        response = AssistantResponse(
            answer=_strip_source_aliases(llm_resp.answer),
            confidence=llm_resp.confidence,
            sources=_verify_used_sources(llm_resp.used_sources, alias_map),
        )
    except Exception as e:
        logger.warning("Structured LLM Generation failed (%s) → falling back to raw invoke", e)
        try:
            _plain_llm_box = [_build_llm(temperature=0.3, max_retries=0, max_tokens=DOCUMENT_MAX_TOKENS)]

            def _rebuild_plain_llm():
                _plain_llm_box[0] = _build_llm(temperature=0.3, max_retries=0, max_tokens=DOCUMENT_MAX_TOKENS)
                return _plain_llm_box[0]

            raw_resp, _wait2 = _invoke_with_rate_limit(
                _plain_llm_box[0], messages, rebuild_llm=_rebuild_plain_llm,
            )
            _llm_call_count += 1
            parsed_answer = _parse_raw_json_answer(raw_resp.content)
            response = AssistantResponse(
                answer=_strip_source_aliases(parsed_answer if parsed_answer is not None else raw_resp.content),
                confidence=compute_rag_confidence(chunks),
                sources=[],
            )
            sources_fallback_eligible = True
        except Exception as e2:
            logger.error("Raw LLM Generation also failed: %s", e2)
            response = AssistantResponse(
                answer=f"Désolé, une erreur s'est produite lors de la génération. Détails: {str(e2)}",
                sources=[],
                confidence=0.0,
            )

    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    timing["llm_call_count"] = _llm_call_count
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="documentaire", question=question,
        hop_count=0, llm_call_count=_llm_call_count,
        total_time_ms=timing["generation_time"] * 1000,
    )
    return {
        "response": response,
        "raw_answer": response.answer if response else "",
        "timing": timing,
        "sources_fallback_eligible": sources_fallback_eligible,
    }
