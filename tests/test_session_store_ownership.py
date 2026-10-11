"""Sessions are namespaced by authenticated owner_uid."""

from langchain_core.messages import HumanMessage

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
    update_session(
        "discuss_channel_1",
        [HumanMessage(content="alice")],
        owner_uid=10,
    )
    update_session(
        "discuss_channel_1",
        [HumanMessage(content="bob")],
        owner_uid=20,
    )

    alice = get_session("discuss_channel_1", owner_uid=10)
    bob = get_session("discuss_channel_1", owner_uid=20)

    assert alice["chat_history"][0].content == "alice"
    assert bob["chat_history"][0].content == "bob"


def test_clear_session_only_removes_owner_entry():
    update_session("s1", [HumanMessage(content="a")], owner_uid=1)
    update_session("s1", [HumanMessage(content="b")], owner_uid=2)
    clear_session("s1", owner_uid=1)

    assert get_session("s1", owner_uid=1)["chat_history"] == []
    assert get_session("s1", owner_uid=2)["chat_history"][0].content == "b"


def test_owner_uid_required():
    import pytest

    with pytest.raises(ValueError):
        get_session("s1", owner_uid="")
