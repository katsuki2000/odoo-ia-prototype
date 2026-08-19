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
from rag.schemas import AssistantResponse, LLMResponse
from rag.routing import RAGState, _is_out_of_scope, OUT_OF_SCOPE_ANSWER

logger = logging.getLogger(__name__)


def _get_chat_groq():
    import sys
    g = sys.modules.get("rag.graph")
    if g and hasattr(g, "ChatGroq"):
        return g.ChatGroq
    return ChatGroq


def _parse_raw_json_answer(raw_text: str) -> Optional[str]:
    """
    Dette technique (19/08, todo/plan.md Partie 4bis): the raw-invoke
    fallback in generate() calls the LLM with the same SYSTEM_PROMPT used
    for structured output (rag/prompts.py), which instructs the model to
    reply with JSON shaped like {"answer": ..., "sources": ...,
    "confidence": ..., "missing_info": ...}. Before this helper, that raw
    JSON text was assigned directly to AssistantResponse.answer, so the
    user saw an escaped JSON blob instead of a sentence whenever the
    structured-output call failed and this fallback ran.

    Extracts the 'answer' field from that JSON so the fallback path
    produces the same shape of answer as the structured-output path.
    Returns None (never raises) when raw_text isn't the expected JSON
    shape, so the caller can fall back to the raw text unchanged instead
    of silently discarding a plain-text answer.
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

    # Bloc 12 / J46-J48: reasoning-trace + LLM-call-budget instrumentation.
    # "documentaire" is the simplest branch (RAG only, no tool hops) --
    # it exists as the baseline llm_call_count comparator against
    # donnees_erp (Function Calling, up to REACT_RECURSION_LIMIT calls)
    # and code_intelligence (up to CI_MAX_HOPS calls + resolver + synthesis).
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

    from rag.prompts import build_messages

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
    ChatGroqCls = _get_chat_groq()
    try:
        llm = ChatGroqCls(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
        # Enforce structured output to match our schema
        structured_llm = llm.with_structured_output(LLMResponse)
        
        llm_resp = structured_llm.invoke(messages)
        _llm_call_count += 1
        response = AssistantResponse(
            answer=llm_resp.answer,
            confidence=llm_resp.confidence,
            sources=[]
        )
    except Exception as e:
        logger.warning("Structured LLM Generation failed (%s) → falling back to raw invoke", e)
        try:
            llm = ChatGroqCls(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
            raw_resp = llm.invoke(messages)
            _llm_call_count += 1
            # Bloc P4bis fix (19/08): the prompt instructs JSON output, so
            # raw_resp.content is JSON text (see _parse_raw_json_answer
            # docstring) -- parse the 'answer' field out of it instead of
            # showing the raw JSON blob to the user. Falls back to the raw
            # text unchanged if it isn't the expected JSON shape.
            parsed_answer = _parse_raw_json_answer(raw_resp.content)
            response = AssistantResponse(
                answer=parsed_answer if parsed_answer is not None else raw_resp.content,
                confidence=0.85,
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
    # Bloc 12 / J46-J48: documentaire branch never makes tool-call hops --
    # hop_count is always 0 here, which is itself the point of comparison
    # against donnees_erp / code_intelligence in the J48 budget report.
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="documentaire", question=question,
        hop_count=0, llm_call_count=_llm_call_count,
        total_time_ms=timing["generation_time"] * 1000,
    )
    return {"response": response, "raw_answer": response.answer if response else "", "timing": timing}

