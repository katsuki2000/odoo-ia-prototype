"""
core/session_store.py

In-memory thread-safe session store for chat history, last route, and resolved concept.
"""

import threading
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage

# session_id -> {"chat_history": List[BaseMessage], "resolved_concept": Optional[dict], "last_route": Optional[str]}
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def get_session(session_id: str) -> Dict[str, Any]:
    """Return this session's stored state, or a fresh empty one if unseen.

    Never returns None and never raises on an unknown session_id -- callers
    can always read ["chat_history"]/["resolved_concept"]/["last_route"]
    without a presence check first. Returns a shallow copy (new dict, new
    list for chat_history) so a caller mutating the returned value in place
    can never corrupt the stored session without going through
    update_session() -- concurrent requests for the same session_id must
    not see a half-updated history.
    """
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            return {"chat_history": [], "resolved_concept": None, "last_route": None}
        return {
            "chat_history": list(session.get("chat_history", [])),
            "resolved_concept": session.get("resolved_concept"),
            "last_route": session.get("last_route"),
        }


def update_session(
    session_id: str,
    chat_history: List[BaseMessage],
    resolved_concept: Optional[dict] = None,
    last_route: Optional[str] = None,
) -> None:
    """Overwrite this session's stored state.

    Last-write-wins -- no attempt at merging concurrent turns for the same
    session_id, consistent with the "simplest possible PoC" scope of
    H1b-i. resolved_concept and last_route are both actively populated by
    the caller (api/main.py, H1c 2026-08-19 / H1b-ii 2026-08-20) after
    every successful turn, from response.route/response.resolved_concept
    (both set centrally by rag/graph.py's format_output() node).
    """
    with _LOCK:
        _SESSIONS[session_id] = {
            "chat_history": list(chat_history),
            "resolved_concept": resolved_concept,
            "last_route": last_route,
        }


def clear_session(session_id: str) -> None:
    """Remove a session's stored state entirely (e.g. explicit reset)."""
    with _LOCK:
        _SESSIONS.pop(session_id, None)
