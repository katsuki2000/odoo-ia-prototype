"""In-memory thread-safe chat history store, namespaced by authenticated owner and bounded in sessions and messages."""

import threading
from collections import OrderedDict
from typing import List, Union

from langchain_core.messages import BaseMessage

from config.settings import CHAT_HISTORY_MAX_MESSAGES, SESSION_MAX_COUNT

OwnerUid = Union[int, str]

_SESSIONS: "OrderedDict[tuple[OwnerUid, str], List[BaseMessage]]" = OrderedDict()
_LOCK = threading.Lock()


def _owned_key(session_id: str, owner_uid: OwnerUid) -> tuple[OwnerUid, str]:
    if owner_uid is None or str(owner_uid).strip() == "":
        raise ValueError("owner_uid is required")
    return owner_uid, session_id


def get_session(session_id: str, owner_uid: OwnerUid) -> List[BaseMessage]:
    """Return a copy of this owner's chat history, empty if the session is unknown."""
    with _LOCK:
        return list(_SESSIONS.get(_owned_key(session_id, owner_uid), ()))


def update_session(session_id: str, chat_history: List[BaseMessage], *, owner_uid: OwnerUid) -> None:
    """Overwrite this owner's chat history, keeping its last messages; the least recently updated sessions are evicted."""
    key = _owned_key(session_id, owner_uid)
    with _LOCK:
        _SESSIONS[key] = chat_history[-CHAT_HISTORY_MAX_MESSAGES:]
        _SESSIONS.move_to_end(key)
        while len(_SESSIONS) > SESSION_MAX_COUNT:
            _SESSIONS.popitem(last=False)


def clear_session(session_id: str, owner_uid: OwnerUid) -> None:
    with _LOCK:
        _SESSIONS.pop(_owned_key(session_id, owner_uid), None)
