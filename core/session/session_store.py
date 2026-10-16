"""In-memory thread-safe session store for chat history and last route."""

import threading
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import BaseMessage

OwnerUid = Union[int, str]

# owner_uid:session_id -> session state
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def _owned_key(session_id: str, owner_uid: OwnerUid) -> str:
    if owner_uid is None or str(owner_uid).strip() == "":
        raise ValueError("owner_uid is required")
    return f"{owner_uid}:{session_id}"


def get_session(session_id: str, owner_uid: OwnerUid) -> Dict[str, Any]:
    """Return this owner's session state, or a fresh empty one if unseen.

    Never returns None and never raises on an unknown session_id -- callers
    can always read ["chat_history"]/["last_route"]
    without a presence check first. Returns a shallow copy so in-place
    mutation cannot corrupt the store without update_session().
    """
    key = _owned_key(session_id, owner_uid)
    with _LOCK:
        session = _SESSIONS.get(key)
        if session is None:
            return {"chat_history": [], "last_route": None}
        return {
            "chat_history": list(session.get("chat_history", [])),
            "last_route": session.get("last_route"),
        }


def update_session(
    session_id: str,
    chat_history: List[BaseMessage],
    last_route: Optional[str] = None,
    *,
    owner_uid: OwnerUid,
) -> None:
    """Overwrite this owner's session state (last-write-wins)."""
    key = _owned_key(session_id, owner_uid)
    with _LOCK:
        _SESSIONS[key] = {
            "chat_history": list(chat_history),
            "last_route": last_route,
        }


def clear_session(session_id: str, owner_uid: OwnerUid) -> None:
    """Remove this owner's session state entirely."""
    key = _owned_key(session_id, owner_uid)
    with _LOCK:
        _SESSIONS.pop(key, None)
