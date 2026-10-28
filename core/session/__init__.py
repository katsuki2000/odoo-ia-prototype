"""
core/session/__init__.py

Session utilities: reasoning_trace_logger.py and session_store.py.
"""

from .reasoning_trace_logger import (
    _logger,
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
    "_logger",
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
