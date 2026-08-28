"""
rag/generate_node.py

Documentary RAG branch -- generates structured answers from retrieved
document chunks using Groq (or the configured LLM provider).
"""

import json
import logging
import re
import time
from typing import Optional

from langchain_groq import ChatGroq

from config.settings import GROQ_MODEL
from core.schemas import AssistantResponse, LLMResponse
from core.routing import RAGState, _is_out_of_scope, OUT_OF_SCOPE_ANSWER
# Section 263 (todo/contexte.txt): multi-key Groq rotation / rate-limit
# retry, same mechanism already used by the Code Intelligence branch.
from core.llm_client import (
    invoke_with_rate_limit as _invoke_with_rate_limit,
    _current_groq_key,
)

logger = logging.getLogger(__name__)


def _get_chat_groq():
    import sys
    g = sys.modules.get("core.graph")
    if g and hasattr(g, "ChatGroq"):
        return g.ChatGroq
    return ChatGroq


def _build_groq_llm(**kwargs):
    """Construct a ChatGroq client bound to the CURRENT rotation-index Groq
    key (core.llm_client._current_groq_key()) instead of relying on
    ChatGroq's own default (single, env-var-only) key resolution. Keeps
    going through _get_chat_groq() so existing @patch('core.graph.ChatGroq')
    unit tests (tests/test_graph.py) remain unaffected -- only the
    constructor args change, not which class gets instantiated."""
    return _get_chat_groq()(model=GROQ_MODEL, api_key=_current_groq_key(), **kwargs)


def compute_rag_confidence(chunks: list, is_out_of_scope: bool = False) -> float:
    """
    Calcule de façon déterministe un score de confiance (0.0 à 1.0) pour la branche documentaire.
    - 0.0 si hors périmètre ou aucun document retrouvé
    - Utilise le score de reranking / similarité du chunk #1 si disponible
    - Sinon, heuristique déterministe basée sur le nombre de chunks pertinents récupérés
    """
    if is_out_of_scope or not chunks:
        return 0.0

    top_chunk = chunks[0]
    score = top_chunk.get("score") or top_chunk.get("rerank_score")
    if score is not None:
        try:
            val = float(score)
            return max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            pass

    num = len(chunks)
    if num >= 3:
        return 0.90
    elif num == 2:
        return 0.80
    elif num == 1:
        return 0.70
    return 0.50


def _parse_raw_json_answer(raw_text: str) -> Optional[str]:
    """
    Extracts the 'answer' field if the raw text is shaped as JSON.
    Returns None if raw_text is not JSON.
    """
    if not raw_text or not isinstance(raw_text, str):
        return None
    candidate = raw_text.strip()
    # Strip markdown code fences (```json ... ``` or ``` ... ```) if present.
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
        candidate = candidate.strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    return answer


def generate(state: RAGState) -> dict:
    """Generate structured answer using Groq (documentary branch)."""
    import time
    start_time = time.time()
    question = state["question"]
    chunks = state["retrieved_chunks"]
    logger.info("Node [generate]: Building prompt and calling LLM")

    # Reasoning trace and LLM call tracking
    from code_intelligence.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
    _trace_id = new_trace_id()
    _trace_logger = ReasoningTraceLogger()

    # Fast-fail for out of scope
    if _is_out_of_scope(question):
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

    # Fallback if no relevant chunks are found
    if not chunks:
        logger.info("Node [generate]: No chunks retrieved, falling back.")
        response = AssistantResponse(
            answer="Je n'ai pas de source fiable pour répondre à cette question.",
            sources=[],
            confidence=0.0
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="documentaire", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    from core.prompts import build_messages

    # Build context text
    context_text = ""
    for i, chunk in enumerate(chunks):
        doc_text = chunk.get("document", "")
        # Coding rule: dict.get for metadata
        metadata = chunk.get("metadata") or {}
        source = metadata.get("source", "unknown")
        context_text += f"[Source {i+1}: {source}]\n{doc_text}\n\n"

    # Build memory + prompt
    chat_history = state.get("chat_history", [])
    messages = build_messages(question, context_text, chat_history)

    _llm_call_count = 0
    try:
        llm = _build_groq_llm(temperature=0.3, max_retries=0, max_tokens=1024)
        # Enforce structured output to match our schema
        _structured_llm_box = [llm.with_structured_output(LLMResponse)]

        def _rebuild_structured_llm():
            fresh = _build_groq_llm(temperature=0.3, max_retries=0, max_tokens=1024)
            _structured_llm_box[0] = fresh.with_structured_output(LLMResponse)
            return _structured_llm_box[0]

        llm_resp, _wait = _invoke_with_rate_limit(
            _structured_llm_box[0], messages, rebuild_llm=_rebuild_structured_llm,
        )
        _llm_call_count += 1
        response = AssistantResponse(
            answer=llm_resp.answer,
            confidence=llm_resp.confidence,
            sources=[]
        )
    except Exception as e:
        logger.warning("Structured LLM Generation failed (%s) → falling back to raw invoke", e)
        try:
            _plain_llm_box = [_build_groq_llm(temperature=0.3, max_retries=0, max_tokens=1024)]

            def _rebuild_plain_llm():
                _plain_llm_box[0] = _build_groq_llm(temperature=0.3, max_retries=0, max_tokens=1024)
                return _plain_llm_box[0]

            raw_resp, _wait2 = _invoke_with_rate_limit(
                _plain_llm_box[0], messages, rebuild_llm=_rebuild_plain_llm,
            )
            _llm_call_count += 1
            # Bloc P4bis fix (19/08): the prompt instructs JSON output, so
            # raw_resp.content is JSON text (see _parse_raw_json_answer
            # docstring) -- parse the 'answer' field out of it instead of
            # showing the raw JSON blob to the user. Falls back to the raw
            # text unchanged if it isn't the expected JSON shape.
            parsed_answer = _parse_raw_json_answer(raw_resp.content)
            response = AssistantResponse(
                answer=parsed_answer if parsed_answer is not None else raw_resp.content,
                confidence=compute_rag_confidence(chunks),
                sources=[]
            )
        except Exception as e2:
            logger.error("Raw LLM Generation also failed: %s", e2)
            response = AssistantResponse(
                answer=f"Désolé, une erreur s'est produite lors de la génération. Détails: {str(e2)}",
                sources=[],
                confidence=0.0
            )
        
    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    timing["llm_call_count"] = _llm_call_count
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="documentaire", question=question,
        hop_count=0, llm_call_count=_llm_call_count,
        total_time_ms=timing["generation_time"] * 1000,
    )
    return {"response": response, "raw_answer": response.answer if response else "", "timing": timing}

