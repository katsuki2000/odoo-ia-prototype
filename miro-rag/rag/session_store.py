"""
rag/session_store.py

H1b-i (todo/plan.md, Bloc P1 preconditions H1): minimal session persistence.

Context: `session_id` already existed in the payload (widget -> controller ->
FastAPI, see api/main.py AskRequestV1) but was never used server-side --
every call to query_graph() ran with chat_history=[], regardless of the
session_id sent. This was not a design decision about business_resolver or
H1b-ii's "reuse last_resolved_concept when the question is under-specified"
logic -- it was the missing infra brick those depended on.

H1b-ii (2026-08-20, todo/contexte.txt section 64/70) is now implemented on
top of this brick: `resolved_concept` below IS actively consumed --
api/main.py reads it into `last_resolved_concept` and passes it to
query_graph(), which feeds rag/routing.py's _sticky_concept_or_resolve
fallback. (Superseded note, kept for history: this docstring originally
said H1b-ii was "deferred until this brick exists" -- that referred to this
file's own prerequisite status, now satisfied.)

Deliberately the simplest possible implementation for a PoC (explicit
project decision, not an oversight): a single process-wide dict, guarded by
a lock for thread-safety (FastAPI can serve concurrent requests on a
threadpool). No expiry/eviction, no persistence across process restart or
across multiple worker processes -- documented limitations. Swapping this
for SQLite/Redis later is a follow-up behind the same get_session()/
update_session() functions, not a redesign of any caller.

H1c (2026-08-19, todo/plan.md): last_route added alongside chat_history/
resolved_concept for the same reason chat_history itself was added in
H1b-i -- route()'s new sticky-routing fallback (_sticky_route_or_default
in rag/graph.py) needs the PREVIOUS turn's QueryRoute value for this
session to reuse when the CURRENT question carries no keyword signal of
its own. Same persistence discipline as chat_history: last-write-wins,
never guessed or inferred here -- this module only stores and returns
whatever the caller (api/main.py) gives it.
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
