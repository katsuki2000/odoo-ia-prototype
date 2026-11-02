"""P9: typed ORM tools wired into resolve_orm_tools and LangChain wrappers."""

from unittest.mock import MagicMock

import pytest

from config.settings import ORM_CONFIDENCE_WITH_DATA, ORM_CONFIDENCE_WITHOUT_DATA
from core.evidence.evidence import EvidenceSourceType, make_evidence
from core.evidence.evidence_collector import (
    collect_and_clear_evidence,
    record_evidence,
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


@pytest.fixture(autouse=True)
def _turn_evidence():
    start_evidence_collection()
    yield
    collect_and_clear_evidence()


def _record_read(claim="res.partner.search_count -> 2", method="search_count"):
    record_evidence(make_evidence(
        EvidenceSourceType.ORM, claim=claim, source=f"orm_runtime.{method}", value=2, scope={"method": method},
    ))


def test_resolve_orm_tools_exposes_only_generic_read_primitives():
    tools = resolve_orm_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "list_models",
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

    def fake_execute(_tc, _tools):
        _record_read()
        return "search_count", {}, "res.partner.search_count -> 2"

    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", fake_invoke)
    monkeypatch.setattr(node, "execute_tool_call", fake_execute)
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock(
        log_hop=MagicMock(), log_summary=MagicMock()
    ))

    result = node.orm_agent_loop({"question": "Combien de partenaires ?"})
    assert calls["n"] == 2
    assert result["response"].answer == "Il y a 2 partenaires."
    assert [source.snippet for source in result["response"].sources] == ["res.partner.search_count -> 2"]
    assert result["response"].confidence == ORM_CONFIDENCE_WITH_DATA


def _run_loop_with_tool_outcome(
    monkeypatch, answer, record_read, explanation="Le modèle demandé est introuvable.", method="search_count"
):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    replies = iter([
        AIMessage(content="", tool_calls=[{"name": "search_read", "args": {}, "id": "tc1"}]),
        AIMessage(content=answer),
    ])

    def fake_execute(_tc, _tools):
        if record_read:
            _record_read(method=method)
        return "search_read", {}, "observation"

    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", lambda *_a: next(replies))
    monkeypatch.setattr(node, "execute_tool_call", fake_execute)
    monkeypatch.setattr(node, "explain_refusals", lambda _question, _observations: (explanation, 1))
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock())
    return node.orm_agent_loop({"question": "Rapport des ventes ?"})


def test_an_answer_after_only_refused_reads_is_replaced_by_the_explanation_and_cites_no_source(monkeypatch):
    out = _run_loop_with_tool_outcome(monkeypatch, "Ventes : ABC Corp 5000 EUR.", record_read=False)
    response = out["response"]
    assert response.answer == "Le modèle demandé est introuvable."
    assert response.sources == []
    assert response.confidence == ORM_CONFIDENCE_WITHOUT_DATA
    assert out["timing"]["llm_call_count"] == 3


def test_the_fixed_message_replaces_the_answer_when_the_explanation_fails(monkeypatch):
    from erp_data.orm_agent_node import NO_READ_ANSWER

    out = _run_loop_with_tool_outcome(monkeypatch, "Ventes : ABC Corp 5000 EUR.", record_read=False, explanation="")
    assert out["response"].answer == NO_READ_ANSWER


@pytest.mark.parametrize("method", ["get_available_models", "fields_get"])
def test_a_schema_read_alone_does_not_count_as_data(monkeypatch, method):
    out = _run_loop_with_tool_outcome(monkeypatch, "Il y a 14 employés actifs.", record_read=True, method=method)
    response = out["response"]
    assert response.answer == "Le modèle demandé est introuvable."
    assert response.sources == []
    assert response.confidence == ORM_CONFIDENCE_WITHOUT_DATA


def test_an_answer_after_a_successful_read_is_kept(monkeypatch):
    response = _run_loop_with_tool_outcome(monkeypatch, "Il y a 2 partenaires.", record_read=True)["response"]
    assert response.answer == "Il y a 2 partenaires."
    assert len(response.sources) == 1


def test_a_clarifying_question_without_any_tool_call_is_kept(monkeypatch):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", lambda *_a: AIMessage(content="Sur quelle période ?"))
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock())
    response = node.orm_agent_loop({"question": "Rapport des ventes ?"})["response"]
    assert response.answer == "Sur quelle période ?"
    assert response.sources == []


def test_prompt_asks_the_user_for_a_limit_when_a_result_is_truncated():
    assert "limite" in ORM_AGENT_SYSTEM_PROMPT and "display_truncated" in ORM_AGENT_SYSTEM_PROMPT
    assert "valeurs fictives" in ORM_AGENT_SYSTEM_PROMPT


def test_prompt_sends_an_unknown_model_to_list_models_but_a_known_one_to_fields_get():
    assert "Ne devine jamais le nom technique d'un modèle inconnu ou refusé" in ORM_AGENT_SYSTEM_PROMPT
    assert "Un modèle standard d'Odoo que tu connais se lit directement avec fields_get" in ORM_AGENT_SYSTEM_PROMPT
    assert "libellés de rapport" in ORM_AGENT_SYSTEM_PROMPT


def test_prompt_asks_for_business_language_in_the_answer():
    assert "langage métier" in ORM_AGENT_SYSTEM_PROMPT
    assert "ni nom d'outil" in ORM_AGENT_SYSTEM_PROMPT
    assert "cite les" not in ORM_AGENT_SYSTEM_PROMPT


def test_refusal_prompt_forbids_data_and_technical_terms():
    from erp_data.prompts import build_orm_refusal_prompt

    prompt = build_orm_refusal_prompt("Combien de biens ?", ["ORM read refused: model missing"])
    assert "Combien de biens ?" in prompt and "ORM read refused: model missing" in prompt
    assert "Ne donne ni donnée" in prompt


def test_explain_refusals_returns_the_text_or_an_empty_string_on_llm_failure(monkeypatch):
    import erp_data.orm_agent_helpers as helpers

    monkeypatch.setattr(helpers, "_single_answer", lambda _prompt: "  Le modèle est introuvable.  ")
    assert helpers.explain_refusals("q", ["refused"]) == ("Le modèle est introuvable.", 1)

    def failing(_prompt):
        raise RuntimeError("llm down")

    monkeypatch.setattr(helpers, "_single_answer", failing)
    assert helpers.explain_refusals("q", ["refused"]) == ("", 1)


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
