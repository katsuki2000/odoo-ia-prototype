import logging
import re
import threading
import time

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from config.settings import (
    LLM_PROVIDER,
    GROQ_API_KEY,
    GROQ_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_BASE_URL,
)

logger = logging.getLogger(__name__)


# ── Provider-agnostic client factory ──────────────────────────────────────

def get_chat_llm(
    *,
    temperature: float = 0.0,
    max_tokens: "int | None" = None,
    max_retries: int = 0,
    model_kwargs: "dict | None" = None,
):
    if LLM_PROVIDER == "groq":
        return ChatGroq(
            model=GROQ_MODEL,
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            model_kwargs=model_kwargs or {},
        )

    if LLM_PROVIDER == "ollama":
        raise NotImplementedError(
            "LLM_PROVIDER=ollama is not configured yet. Please use 'groq' or 'openrouter'."
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER={LLM_PROVIDER!r} -- expected 'groq', "
        f"'openrouter', or 'ollama' (config/settings.py)."
    )

_llm_call_lock = threading.Lock()
_last_llm_call_time = [0.0]
MIN_LLM_CALL_INTERVAL = 5.0  # Enforce 5.0s minimum spacing between LLM calls


def _parse_reset_seconds(header_value: str, default: float = 20.0) -> float:
    if not header_value:
        return default
    match = re.match(r"(?:(\d+)m)?([\d.]+)s", header_value.strip())
    if not match:
        return default
    minutes = float(match.group(1)) if match.group(1) else 0.0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def _extract_rate_limit_headers(exc: Exception) -> dict:
    for attr_path in ("response", "http_response", "resp"):
        resp = getattr(exc, attr_path, None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        resp = getattr(cause, "response", None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    return {}


class _ToolCallFallback:
    """Stand-in minimal pour un AIMessage : seuls .tool_calls et .content sont lus par la boucle ReAct."""
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


_TOOL_USE_FAILED_RE = re.compile(r"'code':\s*'tool_use_failed'.*?'failed_generation':\s*'(.*?)'\s*\}", re.DOTALL)
_FAILED_GEN_CALL_RE = re.compile(r"<function=(\w+)>(\{.*\})")


def _try_recover_tool_use_failed(exc: Exception):
    msg = str(exc)
    if "tool_use_failed" not in msg:
        return None
    match = _TOOL_USE_FAILED_RE.search(msg)
    if not match:
        return None
    call_match = _FAILED_GEN_CALL_RE.search(match.group(1))
    if not call_match:
        return None
    fn_name, args_raw = call_match.group(1), call_match.group(2)
    try:
        import json
        args = json.loads(args_raw)
    except Exception:
        return None
    logger.warning("Récupération d'un tool_call malformé via failed_generation: %s(%s)", fn_name, args)
    return _ToolCallFallback([{"name": fn_name, "args": args, "id": f"fallback_{fn_name}", "type": "tool_call"}])


_TOOL_MSG_HARD_CAP = 400


def _reduce_message_context(messages: list) -> list:
    reduced = []
    for msg in messages:
        if (
            isinstance(msg, ToolMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > _TOOL_MSG_HARD_CAP
        ):
            reduced.append(
                ToolMessage(
                    content=(
                        msg.content[:_TOOL_MSG_HARD_CAP]
                        + "\n[... tronqué pour respecter la limite de taille de requête ...]"
                    ),
                    tool_call_id=msg.tool_call_id,
                )
            )
        elif (
            isinstance(msg, SystemMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > 1000
        ):
            reduced.append(
                SystemMessage(
                    content=(
                        msg.content[:1000]
                        + "\n[... tronqué pour respecter la limite de taille ...]"
                    )
                )
            )
        elif (
            isinstance(msg, HumanMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > 1500
        ):
            reduced.append(
                HumanMessage(
                    content=(
                        msg.content[:1500]
                        + "\n[... tronqué pour respecter la limite de taille de requête ...]"
                    )
                )
            )
        else:
            reduced.append(msg)
    return reduced


def invoke_with_rate_limit(llm_with_tools, messages, max_retries: int = 5):
    context_reduced = False
    total_wait_seconds = 0.0
    for attempt in range(max_retries):
        with _llm_call_lock:
            elapsed = time.time() - _last_llm_call_time[0]
            if elapsed < MIN_LLM_CALL_INTERVAL:
                gap = MIN_LLM_CALL_INTERVAL - elapsed
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
                    logger.error(
                        "Payload still too large after retries -- aborting: %s", err_str,
                    )
                    raise

                # Cas 1 : rate limit (comportement existant, inchangé)
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

                # Cas 2 : tool_use_failed (Groq) -- tenter la récupération, sinon retry renforcé
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

                # Cas 3 : erreurs de connexion transitoires -- retry générique
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
