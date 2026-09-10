"""
core/llm/__init__.py

Regroupement (todo/contexte.txt Section 649-653) : llm_client.py, llm_retry.py.
"""

from .llm_client import (
    logger,
    _groq_key_lock,
    _groq_key_index,
    _current_groq_key,
    _rotate_groq_key,
    _get_chat_groq,
    get_chat_llm,
    _llm_call_lock,
    _last_llm_call_time,
    MIN_LLM_CALL_INTERVAL,
    _get_min_interval,
    invoke_with_rate_limit,
)
from .llm_retry import (
    _TOOL_MSG_HARD_CAP,
    _TOOL_USE_FAILED_RE,
    _FAILED_GEN_CALL_RE,
    ToolCallFallback,
    parse_reset_seconds,
    extract_rate_limit_headers,
    try_recover_tool_use_failed,
    reduce_message_context,
)

__all__ = [
    "logger",
    "_groq_key_lock",
    "_groq_key_index",
    "_current_groq_key",
    "_rotate_groq_key",
    "_get_chat_groq",
    "get_chat_llm",
    "_llm_call_lock",
    "_last_llm_call_time",
    "MIN_LLM_CALL_INTERVAL",
    "_get_min_interval",
    "invoke_with_rate_limit",
    "_TOOL_MSG_HARD_CAP",
    "_TOOL_USE_FAILED_RE",
    "_FAILED_GEN_CALL_RE",
    "ToolCallFallback",
    "parse_reset_seconds",
    "extract_rate_limit_headers",
    "try_recover_tool_use_failed",
    "reduce_message_context",
]
