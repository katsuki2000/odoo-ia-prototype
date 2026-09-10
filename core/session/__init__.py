"""
core/session/__init__.py

Regroupement (todo/contexte.txt Section 649-653) : smalltalk.py, reasoning_trace_logger.py, session_store.py.
"""

from .smalltalk import (
    _GREETING_RE,
    _THANKS_FAREWELL_RE,
    _CONVERSATIONAL_FILLER_RE,
    _ACKNOWLEDGMENT_RE,
    _PUNCTUATION_RE,
    _WHITESPACE_RE,
    _fold_accents,
    classify_smalltalk,
    SMALLTALK_RESPONSES,
)
from .reasoning_trace_logger import (
    _logger,
    MAX_HOPS_PER_QUESTION,
    ReasoningHop,
    ReasoningSummary,
    ReasoningTraceLogger,
    new_trace_id,
)
from .session_store import (
    _SESSIONS,
    _LOCK,
    get_session,
    update_session,
    clear_session,
)

__all__ = [
    "_GREETING_RE",
    "_THANKS_FAREWELL_RE",
    "_CONVERSATIONAL_FILLER_RE",
    "_ACKNOWLEDGMENT_RE",
    "_PUNCTUATION_RE",
    "_WHITESPACE_RE",
    "_fold_accents",
    "classify_smalltalk",
    "SMALLTALK_RESPONSES",
    "_logger",
    "MAX_HOPS_PER_QUESTION",
    "ReasoningHop",
    "ReasoningSummary",
    "ReasoningTraceLogger",
    "new_trace_id",
    "_SESSIONS",
    "_LOCK",
    "get_session",
    "update_session",
    "clear_session",
]
