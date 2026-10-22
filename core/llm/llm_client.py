"""LLM client factory and retry/rate-limit wrapper."""

import logging
import threading
import time
from typing import Any, Callable, Optional, Tuple

from langchain_core.messages import SystemMessage

from config.settings import (
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_API_KEY,
    LLM_NO_THINK_MARKER,
    require_inference_server,
)
from core.llm.llm_retry import (
    ToolCallFallback as _ToolCallFallback,
    parse_reset_seconds as _parse_reset_seconds,
    extract_rate_limit_headers as _extract_rate_limit_headers,
    try_recover_tool_use_failed as _try_recover_tool_use_failed,
    reduce_message_context as _reduce_message_context,
    _TOOL_MSG_HARD_CAP,
    _TOOL_USE_FAILED_RE,
    _FAILED_GEN_CALL_RE,
)

logger = logging.getLogger(__name__)


# ── Client factory ──────────────────────────────────────

def with_no_think(prompt: str) -> str:
    return f"{prompt} {LLM_NO_THINK_MARKER}" if LLM_NO_THINK_MARKER else prompt


def get_chat_llm(
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    max_retries: int = 0,
    model_kwargs: Optional[dict] = None,
):
    """Build the chat client for the configured Ollama server (OpenAI-compatible API)."""
    from langchain_openai import ChatOpenAI
    kw = dict(model_kwargs or {})
    penalties = {name: kw.pop(name) for name in ("frequency_penalty", "presence_penalty") if kw.get(name) is not None}
    return ChatOpenAI(
        model=model or LLM_MODEL,
        base_url=require_inference_server(base_url or LLM_BASE_URL),
        api_key=api_key or LLM_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        model_kwargs=kw,
        **penalties,
    )


# ── Invocation wrapper with rate limiting & error recovery ─────────────────

_llm_call_lock = threading.Lock()
_last_llm_call_time = [0.0]
MIN_LLM_CALL_INTERVAL = 0.0


def _get_min_interval() -> float:
    return MIN_LLM_CALL_INTERVAL


def invoke_with_rate_limit(
    llm_with_tools,
    messages: list,
    max_retries: int = 5,
    rebuild_llm: Optional[Callable[[], Any]] = None,
) -> Tuple[Any, float]:
    """Execute LLM invocation with spacing, context truncation, and key rotation on rate limits."""
    context_reduced = False
    total_wait_seconds = 0.0
    min_interval = _get_min_interval()
    for attempt in range(max_retries):
        with _llm_call_lock:
            elapsed = time.time() - _last_llm_call_time[0]
            if min_interval > 0 and elapsed < min_interval:
                gap = min_interval - elapsed
                time.sleep(gap)
                total_wait_seconds += gap
            try:
                result = llm_with_tools.invoke(messages)
                _last_llm_call_time[0] = time.time()
                if hasattr(result, "response_metadata"):
                    logger.info("LLM DIAGNOSTIC METADATA: %s", result.response_metadata)
                return result, total_wait_seconds
            except Exception as e:
                _last_llm_call_time[0] = time.time()
                err_str = str(e)

                is_too_large = (
                    "413" in err_str
                    or "request too large" in err_str.lower()
                    or "reduce your message size" in err_str.lower()
                    or "context_length_exceeded" in err_str.lower()
                    or "maximum context length" in err_str.lower()
                )
                if is_too_large:
                    if not context_reduced:
                        messages = _reduce_message_context(messages)
                        context_reduced = True
                        logger.warning(
                            "Payload too large (413, attempt %d/%d) -- contexte réduit, "
                            "nouvelle tentative immédiate.",
                            attempt + 1, max_retries,
                        )
                        continue
                    elif attempt < max_retries - 1:
                        wait_time = 10.0
                        logger.warning(
                            "Still too large after context reduction (attempt %d/%d) -- "
                            "waiting %.1fs before retry.",
                            attempt + 1, max_retries, wait_time,
                        )
                        time.sleep(wait_time)
                        total_wait_seconds += wait_time
                        continue
                    logger.error("Payload still too large after retries -- aborting: %s", err_str)
                    raise

                is_rate_limit = "429" in err_str or "rate_limit" in err_str.lower()
                if is_rate_limit and attempt < max_retries - 1:
                    headers = _extract_rate_limit_headers(e)
                    reset_raw = (
                        headers.get("x-ratelimit-reset-tokens")
                        or headers.get("x-ratelimit-reset-requests")
                    )
                    wait_time = _parse_reset_seconds(reset_raw, default=2 ** attempt * 5.0)
                    wait_time += 0.5
                    logger.warning(
                        "Rate limit hit (attempt %d/%d). Headers: %s. Dynamically waiting %.1fs...",
                        attempt + 1, max_retries,
                        {k: v for k, v in headers.items() if "ratelimit" in k.lower()},
                        wait_time,
                    )
                    time.sleep(wait_time)
                    total_wait_seconds += wait_time
                    continue

                if "tool_use_failed" in err_str:
                    recovered = _try_recover_tool_use_failed(e)
                    if recovered is not None:
                        return recovered, total_wait_seconds
                    if attempt < max_retries - 1:
                        logger.warning(
                            "tool_use_failed non récupérable (attempt %d/%d), retry avec instruction renforcée.",
                            attempt + 1, max_retries,
                        )
                        messages = messages + [
                            SystemMessage(content=(
                                "RAPPEL STRICT : réponds UNIQUEMENT via un appel d'outil structuré "
                                "(tool_call). N'écris jamais de pseudo-appel en texte libre du type "
                                "<function=...>{...}>."
                            ))
                        ]
                        wait_time = 1.0
                        time.sleep(wait_time)
                        total_wait_seconds += wait_time
                        continue
                    raise

                is_connection_error = any(
                    term in err_str.lower()
                    for term in ("connection", "timeout", "timed out", "temporarily unavailable")
                )
                if is_connection_error and attempt < max_retries - 1:
                    wait_time = 2 ** attempt * 3.0
                    logger.warning(
                        "Erreur de connexion transitoire (attempt %d/%d): %s. Retry dans %.1fs...",
                        attempt + 1, max_retries, err_str, wait_time,
                    )
                    time.sleep(wait_time)
                    total_wait_seconds += wait_time
                    continue

                raise
