"""Sessions are namespaced by authenticated owner_uid and bounded in number."""

import pytest
from langchain_core.messages import HumanMessage

from core.session import session_store
from core.session.session_store import (
    _SESSIONS,
    clear_session,
    get_session,
    update_session,
)


def setup_function():
    _SESSIONS.clear()


def teardown_function():
    _SESSIONS.clear()


def test_same_session_id_isolated_per_owner():
    update_session("discuss_channel_1", [HumanMessage(content="alice")], owner_uid=10)
    update_session("discuss_channel_1", [HumanMessage(content="bob")], owner_uid=20)

    assert get_session("discuss_channel_1", owner_uid=10)[0].content == "alice"
    assert get_session("discuss_channel_1", owner_uid=20)[0].content == "bob"


def test_clear_session_only_removes_owner_entry():
    update_session("s1", [HumanMessage(content="a")], owner_uid=1)
    update_session("s1", [HumanMessage(content="b")], owner_uid=2)
    clear_session("s1", owner_uid=1)

    assert get_session("s1", owner_uid=1) == []
    assert get_session("s1", owner_uid=2)[0].content == "b"


def test_owner_uid_required():
    with pytest.raises(ValueError):
        get_session("s1", owner_uid="")


def test_least_recently_updated_session_is_evicted(monkeypatch):
    monkeypatch.setattr(session_store, "SESSION_MAX_COUNT", 2)
    for name in ("s1", "s2"):
        update_session(name, [HumanMessage(content=name)], owner_uid=1)
    update_session("s1", [HumanMessage(content="s1 again")], owner_uid=1)
    update_session("s3", [HumanMessage(content="s3")], owner_uid=1)

    assert get_session("s2", owner_uid=1) == []
    assert get_session("s1", owner_uid=1)[0].content == "s1 again"
    assert get_session("s3", owner_uid=1)[0].content == "s3"
