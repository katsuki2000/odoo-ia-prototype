"""
rag/llm_client.py

Centralized LLM client factory + call-retry infrastructure.

Extracted 2026-08-14 from rag/graph.py, which used to instantiate ChatGroq
directly at 7 separate call sites, all hardcoding GROQ_MODEL/GROQ_API_KEY --
LLM_PROVIDER existed in config/settings.py since the project's early days
but was never actually read anywhere (a dead flag). This module is the
first real provider switch: get_chat_llm() branches on LLM_PROVIDER and
returns the right langchain chat model, so a call site never imports
ChatGroq/ChatOpenAI directly again.

Scope of this refactor (2026-08-14, requested to unblock testing
Qwen3-14B ahead of the paused Bloc 9bis local-inference validation --
OpenRouter's free qwen/qwen3-14b:free tier as an interim step, same model
weights as the eventual local target): only code_intelligence_agent's two
LLM instantiations (the ReAct loop + the synthesis call) were switched to
use get_chat_llm() -- that is the one branch the Bloc 9 adversarial
benchmark (scripts/check_bloc9_*.py) actually exercises. generate()
(documentaire branch), orm_agent_loop() (donnees_erp/Function-Calling
branch), and hybrid_node() still instantiate ChatGroq directly and are
UNTOUCHED by this refactor -- deliberately, not an oversight:
  1. generate() is covered by tests/test_graph.py::test_query_graph_mocked,
     which does `@patch('core.graph.ChatGroq')` -- routing that call through
     this factory would silently stop being patchable by that test (the
     mock would patch rag.graph.ChatGroq, but the actual call would go
     through rag.llm_client.ChatGroq, a different name), breaking a test
     without any execution access on this machine to catch it.
  2. Nothing about the Qwen3-14B evaluation needs those branches -- the
     Bloc 9 adversarial questions all route through code_intelligence_agent.
Widening this factory to the other 3 branches is a natural, low-risk
follow-up (each one is a strict ChatGroq(...) call site replaced with
get_chat_llm(...), same shape as the two done here) but was not done this
session to keep the diff scoped to what the immediate goal needs, per
rules.md ("pas de fix chirurgical, voir la root cause" cuts both ways --
the root cause here is "no factory for the Code Intelligence branch",
not "every LLM call in the file must move in the same pass").

LLM_PROVIDER values supported:
  - "groq"       : existing behavior, unchanged (ChatGroq, GROQ_MODEL).
  - "openrouter" : new. ChatOpenAI pointed at OpenRouter's OpenAI-compatible
                   endpoint (OPENROUTER_MODEL, default qwen/qwen3-14b:free).
  - "ollama"     : NOT YET IMPLEMENTED. config/settings.py has carried
                   OLLAMA_HOST/OLLAMA_MODEL placeholders since early on, but
                   Bloc 9bis (the plan item that would have wired this in)
                   is on hold pending local GPU hardware -- raises a clear
                   NotImplementedError rather than silently falling through
                   to a wrong provider, per rules.md Regle 5 (exhaustive
                   handling, no silent fallback).
"""

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
    """
    Return a langchain chat model instance for the currently configured
    LLM_PROVIDER (config/settings.py, env var LLM_PROVIDER -- default
    "groq", unchanged from before this refactor).

    model_kwargs is passed straight through to the underlying client's own
    model_kwargs (both ChatGroq and ChatOpenAI forward unknown OpenAI-style
    body params this way -- parallel_tool_calls/frequency_penalty/
    presence_penalty are all standard OpenAI Chat Completions fields, which
    is exactly why OpenRouter, being OpenAI-compatible, accepts the same
    kwargs unchanged; this was verified against OpenRouter's own published
    API reference, not assumed).
    """
    if LLM_PROVIDER == "groq":
        return ChatGroq(
            model=GROQ_MODEL,
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            model_kwargs=model_kwargs or {},
        )

    if LLM_PROVIDER == "openrouter":
        # Imported lazily: langchain-openai is a new dependency (see
        # requirements.txt) -- keeps the groq-only path free of an import
        # error if the package isn't installed yet on a machine that never
        # sets LLM_PROVIDER=openrouter.
        from langchain_openai import ChatOpenAI

        if not OPENROUTER_API_KEY:
            raise RuntimeError(
                "LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is not set "
                "(config/settings.py / .env). Get a free key at "
                "https://openrouter.ai/settings/keys."
            )
        return ChatOpenAI(
            model=OPENROUTER_MODEL,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            model_kwargs=model_kwargs or {},
            # OpenRouter-recommended (not required) attribution headers --
            # helps OpenRouter's own dashboard/rate-limit accounting
            # attribute traffic to this app. Harmless if OpenRouter ignores
            # them; never sent to Groq.
            default_headers={
                "HTTP-Referer": "https://github.com/miro-ke/odoo-ia-prototype",
                "X-Title": "MIRO Code Intelligence",
            },
        )

    if LLM_PROVIDER == "ollama":
        raise NotImplementedError(
            "LLM_PROVIDER=ollama is not wired up yet -- Bloc 9bis (local "
            "inference validation) is on hold pending GPU hardware. See "
            "todo/real plan.md, Bloc 9bis. OPENROUTER_MODEL currently "
            "defaults to the same model family (qwen/qwen3-14b) you would "
            "eventually run locally via Ollama, as an interim cloud "
            "validation step -- see llm_client.py's own module docstring."
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER={LLM_PROVIDER!r} -- expected 'groq', "
        f"'openrouter', or 'ollama' (config/settings.py)."
    )


# ── Call-retry infrastructure (moved verbatim from rag/graph.py, minor
#    generalization noted inline where it touches provider-specific string
#    matching) ────────────────────────────────────────────────────────────

_llm_call_lock = threading.Lock()
_last_llm_call_time = [0.0]
MIN_LLM_CALL_INTERVAL = 5.0  # Enforce 5.0s minimum spacing between LLM calls


def _parse_reset_seconds(header_value: str, default: float = 20.0) -> float:
    """
    Groq's x-ratelimit-reset-* headers come as e.g. '13.42s' or '1m3.42s'.
    Parse into a plain float number of seconds. Other providers (e.g.
    OpenRouter) may not send these headers at all -- callers already treat
    a missing/unparseable header as "use the exponential-backoff default",
    so this stays a no-op (falls through to default) rather than needing a
    second provider-specific parser.
    """
    if not header_value:
        return default
    match = re.match(r"(?:(\d+)m)?([\d.]+)s", header_value.strip())
    if not match:
        return default
    minutes = float(match.group(1)) if match.group(1) else 0.0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def _extract_rate_limit_headers(exc: Exception) -> dict:
    """
    Best-effort extraction of rate-limit headers from whatever exception
    the underlying HTTP client raises on a 429. Provider-agnostic by
    construction (just walks common attribute names for an HTTP response
    object) -- returns {} if nothing matches, which callers already treat
    as "no headers available, use the exponential-backoff default".
    """
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
    """
    llama-3.1-8b-instant (via Groq) régresse parfois vers un pattern texte
    '<function=NOM>{...}' au lieu d'un tool_call structuré, ce que l'API
    Groq rejette en 400 tool_use_failed. On récupère l'intention par regex
    plutôt que de perdre le tour. Retourne None si le payload n'est pas
    récupérable (laisse la place au retry).

    Groq-specific error shape ('tool_use_failed' is a Groq error code) --
    self-guarding via the string match below, so this is a safe no-op for
    any other provider's differently-shaped tool-calling errors, not just
    for Groq.
    """
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
    """
    A 413 (payload too large) response has a FIXED request size -- unlike a
    429, resending the identical messages after a wait will never succeed,
    since the token count doesn't change on its own. This shrinks the
    largest, most compressible part of the payload (ToolMessage and
    HumanMessage synthesis prompts).
    """
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
    """
    Invoke le LLM avec :
      - espacement minimal entre appels
      - backoff dynamique sur 429 (headers x-ratelimit-reset-tokens quand fournis par le provider)
      - réduction de contexte sur 413 / "too large" (attendre ne sert à rien)
      - récupération / retry renforcé sur tool_use_failed (Groq)
      - retry générique avec backoff exponentiel sur erreurs de connexion transitoires

    Returns (result, wait_seconds) where wait_seconds is the total time spent
    sleeping for rate-limit backoffs and minimum-interval enforcement -- callers
    subtract this from wall-clock to get effective (algorithmic) latency.
    (J30-J31: performance instrumentation.)

    Renamed from the private _invoke_with_rate_limit (rag/graph.py) during
    the 2026-08-14 llm_client.py extraction -- re-exported into rag.graph's
    namespace under the old name for backward compatibility with existing
    test imports (tests/code_intelligence/tests/test_j30_31_latency_budget.py
    does `from core.graph import CI_MAX_HOPS, _invoke_with_rate_limit`).
    """
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

                # Cas 0 : payload trop gros (413). Certains providers (Groq
                # confirmed) renvoient aussi 'code': 'rate_limit_exceeded' sur
                # ce cas, ce qui le ferait tomber dans le Cas 1 ci-dessous et
                # partir en backoff exponentiel alors que la requête a une
                # taille FIXE : attendre ne réduit jamais son nombre de
                # tokens, donc chaque nouvelle tentative répète exactement le
                # même échec. Detection broadened (2026-08-14) to also catch
                # OpenAI-compatible providers' context-length-exceeded
                # phrasing (OpenRouter is OpenAI-compatible) -- unverified
                # against a real OpenRouter overflow this session (no
                # execution access), kept alongside the original Groq-
                # specific phrasing rather than replacing it, so Groq's
                # already-confirmed behavior cannot regress.
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
