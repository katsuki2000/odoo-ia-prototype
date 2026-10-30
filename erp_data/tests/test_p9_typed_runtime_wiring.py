"""P9: typed ORM tools wired into resolve_orm_tools and LangChain wrappers."""

from unittest.mock import MagicMock

import pytest

from core.evidence.evidence_collector import (
    collect_and_clear_evidence,
    start_evidence_collection,
)
from erp_data.odoo_context import odoo_uid_ctx
from erp_data.orm_agent_helpers import resolve_orm_tools
from erp_data.prompts import ORM_AGENT_SYSTEM_PROMPT, build_orm_agent_messages
from erp_data.runtime import read_tools


@pytest.fixture(autouse=True)
def _reset_connector():
    read_tools._connector = None
    yield
    read_tools._connector = None


def test_resolve_orm_tools_exposes_only_generic_read_primitives():
    tools = resolve_orm_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "fields_get",
        "search",
        "read",
        "search_read",
        "search_count",
        "read_group",
        "name_search",
    }


def test_orm_prompt_requires_instance_schema_and_evidence():
    messages = build_orm_agent_messages("Combien de partenaires ?")
    assert messages[0].content == ORM_AGENT_SYSTEM_PROMPT
    assert "modules personnalisés" in messages[0].content
    assert "Ne suppose jamais qu'un modèle" in messages[0].content
    assert "seule source de faits" in messages[0].content


def test_search_count_wrapper_records_evidence_and_returns_json():
    from erp_data.runtime.langchain_tools import search_count

    connector = MagicMock()
    connector.search_count.return_value = 42
    read_tools._connector = connector
    token = odoo_uid_ctx.set(11)
    start_evidence_collection()
    try:
        text = search_count.invoke({"model": "res.partner", "domain": []})
    finally:
        odoo_uid_ctx.reset(token)
    dossier = collect_and_clear_evidence()

    assert "search_count -> 42" in text
    assert '"value": 42' in text or '"value":42' in text
    assert len(dossier) == 1
    assert dossier[0].value == 42
    assert dossier[0].scope["execution_identity"] == 11


def test_name_search_wrapper_refuses_invalid_model():
    from erp_data.runtime.langchain_tools import name_search

    token = odoo_uid_ctx.set(1)
    try:
        text = name_search.invoke({"model": "BAD", "name": "x"})
    finally:
        odoo_uid_ctx.reset(token)
    assert text.startswith("ORM read refused:")


def test_orm_agent_loop_allows_second_hop_after_tool_observation(monkeypatch):
    """Multi-hop: after a tool result, the LLM must get another turn (typed tools need it)."""
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    calls = {"n": 0}

    def fake_invoke(_llm, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "search_count",
                    "args": {"model": "res.partner", "domain": []},
                    "id": "tc1",
                }],
            )
        return AIMessage(content="Il y a 2 partenaires.")

    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", fake_invoke)
    monkeypatch.setattr(
        node,
        "execute_tool_call",
        lambda _tc, _tools: ("search_count", {}, "res.partner.search_count -> 2"),
    )
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock(
        log_hop=MagicMock(), log_summary=MagicMock()
    ))

    result = node.orm_agent_loop({"question": "Combien de partenaires ?"})
    assert calls["n"] == 2
    assert result["response"].answer == "Il y a 2 partenaires."


def test_prompt_has_no_model_discovery_tool_and_trusts_fields_get():
    assert "find_models" not in ORM_AGENT_SYSTEM_PROMPT
    assert "inconnu jusqu'à" not in ORM_AGENT_SYSTEM_PROMPT


def test_fields_get_wrapper_shows_every_field_of_a_large_model():
    from erp_data.runtime.langchain_tools import fields_get

    connector = MagicMock()
    connector.fields_get.return_value = {
        **{f"field_{number:03d}": {"type": "char", "string": f"Label {number}"} for number in range(170)},
        "state": {"type": "selection", "string": "Status"},
    }
    read_tools._connector = connector
    token = odoo_uid_ctx.set(11)
    start_evidence_collection()
    try:
        text = fields_get.invoke({"model": "sale.order"})
    finally:
        odoo_uid_ctx.reset(token)
    collect_and_clear_evidence()

    assert "display_truncated" not in text
    assert "field_169" in text and "state" in text
    assert "field_names" in fields_get.args


def test_an_empty_reply_is_sent_back_to_the_model_instead_of_becoming_the_answer(monkeypatch):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node
    from erp_data.prompts import EMPTY_REPLY_REMINDER

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    replies = iter([AIMessage(content="  "), AIMessage(content="Il y a 2 partenaires.")])
    seen = []

    def fake_invoke(_llm, messages):
        seen.append(messages[-1].content)
        return next(replies)

    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", fake_invoke)
    result = node.orm_agent_loop({"question": "Combien de partenaires ?"})
    assert result["response"].answer == "Il y a 2 partenaires."
    assert seen[1] == EMPTY_REPLY_REMINDER
    assert result["timing"]["llm_call_count"] == 2
