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
from erp_data.orm_agent_helpers import QueryPlan, plan_orm_question, resolve_orm_tools
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


def test_orm_domain_schema_requires_triplets_and_rejects_object_leaves():
    from pydantic import ValidationError

    from erp_data.runtime.langchain_tools import search_count

    schema = search_count.args_schema.model_json_schema()["properties"]["domain"]
    items = next(option["items"] for option in schema["anyOf"] if option.get("type") == "array")
    leaf_schema = next(option for option in items["anyOf"] if option.get("type") == "array")
    assert leaf_schema["prefixItems"][:2] == [{"type": "string"}, {"type": "string"}]
    assert leaf_schema["minItems"] == leaf_schema["maxItems"] == 3

    parsed = search_count.args_schema.model_validate({
        "model": "purchase.order",
        "domain": [["state", "=", "purchase"]],
    })
    assert parsed.domain == [("state", "=", "purchase")]
    with pytest.raises(ValidationError):
        search_count.args_schema.model_validate({
            "model": "purchase.order",
            "domain": [{"field": "state", "operator": "=", "value": "purchase"}],
        })


POSTED = ("state", "=", "posted")
UNPAID = ("payment_state", "=", "not_paid")


def _plan(conditions, subject_scope="model"):
    return QueryPlan(
        subject="customer invoices", subject_scope=subject_scope, conditions=conditions,
        result_kind="count", answer_language="English",
    )


def _tool(name):
    from erp_data.runtime import langchain_tools

    tool = MagicMock()
    tool.name = name
    tool.args_schema = getattr(langchain_tools, name).args_schema
    tool.invoke = MagicMock(return_value="4 records")
    return tool


def test_domain_covers_the_plan_with_one_filter_per_condition():
    from erp_data.orm_agent_helpers import domain_covers_plan

    plan = _plan(["posted", "unpaid"])

    assert domain_covers_plan(plan, "search_count", {"domain": [POSTED, UNPAID]}) is True
    assert domain_covers_plan(plan, "search_count", {"domain": ["|", POSTED, UNPAID]}) is True
    assert domain_covers_plan(plan, "search_count", {"domain": [POSTED]}) is False
    assert domain_covers_plan(_plan(["posted"]), "search_count", {"domain": ["|"]}) is False
    assert domain_covers_plan(plan, "search_count", {}) is False


def test_a_subset_subject_needs_one_more_filter():
    from erp_data.orm_agent_helpers import domain_covers_plan

    plan = _plan(["posted"], subject_scope="subset")
    subject = ("move_type", "=", "out_invoice")

    assert domain_covers_plan(plan, "search_count", {"domain": [POSTED]}) is False
    assert domain_covers_plan(plan, "search_count", {"domain": [subject, POSTED]}) is True


def test_domain_coverage_is_not_measured_without_a_plan_or_for_schema_tools():
    from erp_data.orm_agent_helpers import domain_covers_plan

    assert domain_covers_plan(None, "search_count", {}) is False
    assert domain_covers_plan(_plan(["posted"]), "fields_get", {}) is False
    assert domain_covers_plan(_plan([]), "search_count", {"domain": []}) is True


def test_domain_schema_flattens_nested_fragments():
    from erp_data.runtime.langchain_tools import search_count

    parsed = search_count.args_schema.model_validate({
        "model": "account.move",
        "domain": [
            [["move_type", "=", "out_invoice"], ["payment_state", "=", "not_paid"]],
            [["state", "=", "posted"]],
        ],
    }).model_dump(exclude_none=True)

    assert parsed["domain"] == [("move_type", "=", "out_invoice"), UNPAID, POSTED]


def test_execute_tool_call_runs_a_domain_that_misses_a_condition_and_reports_it():
    from erp_data.orm_agent_helpers import execute_tool_call

    tool = _tool("search_count")
    name, arguments, observation, covers_plan = execute_tool_call(
        {"name": "search_count", "args": {"model": "account.move", "domain": [list(POSTED)]}},
        [tool], _plan(["posted", "unpaid"]),
    )

    assert name == "search_count"
    assert observation == "4 records"
    assert covers_plan is False
    tool.invoke.assert_called_once_with(arguments)


def test_execute_tool_call_runs_a_domain_that_covers_the_plan():
    from erp_data.orm_agent_helpers import execute_tool_call

    tool = _tool("search_count")
    raw_args = {"model": "account.move", "domain": [list(POSTED), list(UNPAID)]}

    _name, arguments, observation, covers_plan = execute_tool_call(
        {"name": "search_count", "args": raw_args}, [tool], _plan(["posted", "unpaid"]),
    )

    assert observation == "4 records"
    assert covers_plan is True
    assert arguments["domain"] == [POSTED, UNPAID]
    tool.invoke.assert_called_once_with(arguments)


def test_execute_tool_call_tells_the_model_why_its_arguments_were_rejected():
    from erp_data.orm_agent_helpers import execute_tool_call

    tool = _tool("list_models")
    _name, _arguments, observation, covers_plan = execute_tool_call(
        {"name": "list_models", "args": {"filter": "fiscal"}}, [tool],
    )

    assert observation == "Query refused: invalid arguments for list_models: query: Field required"
    assert covers_plan is False
    tool.invoke.assert_not_called()


def test_condition_filters_is_no_longer_part_of_the_tool_contract():
    from erp_data.runtime.langchain_tools import TYPED_ORM_LANGCHAIN_TOOLS

    assert all("condition_filters" not in tool.args for tool in TYPED_ORM_LANGCHAIN_TOOLS)


def test_orm_prompt_documents_the_odoo_domain_shape():
    from erp_data.orm_agent_helpers import format_query_plan

    assert "liste de triplets [champ, opérateur, valeur]" in ORM_AGENT_SYSTEM_PROMPT
    assert "N'envoie jamais une condition sous forme d'objet" in ORM_AGENT_SYSTEM_PROMPT
    assert "condition_filters" not in ORM_AGENT_SYSTEM_PROMPT
    assert "subject_scope" in ORM_AGENT_SYSTEM_PROMPT
    assert "ne demande aucun filtre" in ORM_AGENT_SYSTEM_PROMPT
    text = format_query_plan(QueryPlan(
        subject="opportunités", subject_scope="subset", conditions=["perdues", "sans motif de perte"],
        result_kind="count", answer_language="français",
    ))
    assert "Sujet obligatoire : opportunités" in text
    assert "Portée du sujet : subset" in text
    assert "au moins" not in text


def test_orm_messages_carry_the_business_plan():
    messages = build_orm_agent_messages("Combien d'opportunités ouvertes ?", query_plan="Conditions: active")
    assert messages[2].content == "Conditions: active"


def test_orm_messages_carry_the_current_date():
    from datetime import datetime, timezone

    messages = build_orm_agent_messages("Combien a-t-on dépensé le mois dernier ?")
    assert messages[1].content == f"Date du jour (UTC) : {datetime.now(timezone.utc).date().isoformat()}."


def test_query_planner_returns_structured_business_constraints(monkeypatch):
    class StructuredPlanner:
        def with_structured_output(self, _schema, method):
            assert method == "json_schema"
            return self

    expected = QueryPlan(
        subject="opportunités",
        conditions=["type opportunité", "actives", "ni gagnées ni perdues"],
        result_kind="count",
        answer_language="français",
    )
    monkeypatch.setattr("erp_data.orm_agent_helpers.invoke_llm", lambda *_args: expected)
    plan, calls = plan_orm_question("Combien d'opportunités ouvertes ?", lambda **_kwargs: StructuredPlanner())
    assert plan == expected
    assert calls == 1


def test_query_planner_keeps_the_compound_subject_available_for_domain_mapping(monkeypatch):
    class StructuredPlanner:
        def with_structured_output(self, _schema, method):
            assert method == "json_schema"
            return self

    raw_plan = QueryPlan(
        subject="factures clients",
        subject_scope="subset",
        conditions=["publiées"],
        result_kind="count",
        answer_language="français",
    )
    monkeypatch.setattr("erp_data.orm_agent_helpers.invoke_llm", lambda *_args: raw_plan)
    plan, calls = plan_orm_question(
        "Combien de factures clients sont publiées ?", lambda **_kwargs: StructuredPlanner()
    )

    assert plan is not None
    assert plan.subject == "factures clients"
    assert plan.subject_scope == "subset"
    assert plan.conditions == ["publiées"]
    assert calls == 1


def test_query_planner_keeps_an_explicit_subject_condition(monkeypatch):
    class StructuredPlanner:
        def with_structured_output(self, _schema, method):
            assert method == "json_schema"
            return self

    raw_plan = QueryPlan(
        subject="customer invoices",
        conditions=["customer invoices", "posted"],
        result_kind="count",
        answer_language="English",
    )
    monkeypatch.setattr("erp_data.orm_agent_helpers.invoke_llm", lambda *_args: raw_plan)
    plan, _calls = plan_orm_question(
        "How many posted customer invoices?", lambda **_kwargs: StructuredPlanner()
    )

    assert plan is not None
    assert plan.conditions == ["customer invoices", "posted"]


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

    def fake_execute(_tc, _tools, _plan=None):
        _record_read()
        return "search_count", {}, "res.partner.search_count -> 2", True

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
    monkeypatch, answer, record_read, explanation="Le modèle demandé est introuvable.", method="search_count",
    plan=None, covers_plan=True, observation="observation",
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

    def fake_execute(_tc, _tools, _plan=None):
        if record_read:
            _record_read(method=method)
        return "search_read", {}, observation, covers_plan

    monkeypatch.setattr(node, "plan_orm_question", lambda *_args: (plan, 0))
    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", lambda *_a: next(replies))
    monkeypatch.setattr(node, "execute_tool_call", fake_execute)
    monkeypatch.setattr(node, "explain_refusals", lambda _question, _observations: (explanation, 1))
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock())
    return node.orm_agent_loop({"question": "Rapport des ventes ?"})


REFUSED = "ORM read refused: model missing"


def test_an_answer_after_only_refused_reads_is_replaced_by_the_explanation_and_cites_no_source(monkeypatch):
    out = _run_loop_with_tool_outcome(
        monkeypatch, "Ventes : ABC Corp 5000 EUR.", record_read=False, observation=REFUSED,
    )
    response = out["response"]
    assert response.answer == "Le modèle demandé est introuvable."
    assert response.sources == []
    assert response.confidence == ORM_CONFIDENCE_WITHOUT_DATA
    assert out["timing"]["llm_call_count"] == 3


def test_the_fixed_message_replaces_the_answer_when_the_explanation_fails(monkeypatch):
    from erp_data.orm_agent_node import NO_READ_ANSWER

    out = _run_loop_with_tool_outcome(
        monkeypatch, "Ventes : ABC Corp 5000 EUR.", record_read=False, explanation="", observation=REFUSED,
    )
    assert out["response"].answer == NO_READ_ANSWER


@pytest.mark.parametrize("method", ["get_available_models", "fields_get"])
def test_a_schema_read_alone_does_not_count_as_data(monkeypatch, method):
    out = _run_loop_with_tool_outcome(
        monkeypatch, "Il y a 14 employés actifs.", record_read=True, method=method, observation=REFUSED,
    )
    response = out["response"]
    assert response.answer == "Le modèle demandé est introuvable."
    assert response.sources == []
    assert response.confidence == ORM_CONFIDENCE_WITHOUT_DATA


@pytest.mark.parametrize("method", ["get_available_models", "fields_get"])
def test_the_answer_is_kept_without_explanation_when_no_tool_failed_and_no_data_was_read(monkeypatch, method):
    out = _run_loop_with_tool_outcome(
        monkeypatch, "Aucun modèle ne correspond à votre question.", record_read=True, method=method,
    )
    response = out["response"]
    assert response.answer == "Aucun modèle ne correspond à votre question."
    assert response.sources == []
    assert response.confidence == ORM_CONFIDENCE_WITHOUT_DATA
    assert out["timing"]["llm_call_count"] == 2


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


def test_an_answer_is_kept_when_the_read_domain_misses_a_plan_condition(monkeypatch):
    from erp_data.orm_agent_helpers import QueryPlan

    plan = QueryPlan(
        subject="customer invoices", conditions=["posted", "unpaid"],
        result_kind="count", answer_language="English",
    )
    response = _run_loop_with_tool_outcome(
        monkeypatch, "Il y a 31 factures.", record_read=True, plan=plan, covers_plan=False,
    )["response"]

    assert response.answer == "Il y a 31 factures."
    assert len(response.sources) == 1


def test_repeated_query_refusals_stop_the_react_loop(monkeypatch):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node
    from erp_data.orm_agent_helpers import QueryPlan
    from erp_data.orm_agent_node import NO_READ_ANSWER

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    calls = {"llm": 0, "tool": 0}

    def fake_invoke(_llm, _messages):
        calls["llm"] += 1
        return AIMessage(content="", tool_calls=[{
            "name": "search_count", "args": {"model": "account.move"}, "id": f"tc{calls['llm']}",
        }])

    def fake_execute(_tool_call, _tools, _plan=None):
        calls["tool"] += 1
        return "search_count", {}, "Query refused: invalid arguments for search_count.", False

    plan = QueryPlan(
        subject="customer invoices", conditions=["posted"],
        result_kind="count", answer_language="English",
    )
    monkeypatch.setattr(node, "plan_orm_question", lambda *_args: (plan, 1))
    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_kwargs: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", fake_invoke)
    monkeypatch.setattr(node, "execute_tool_call", fake_execute)
    monkeypatch.setattr(node, "explain_refusals", lambda _question, _observations: ("", 1))
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock())

    result = node.orm_agent_loop({"question": "How many posted customer invoices?"})

    assert calls == {"llm": 2, "tool": 2}
    assert result["response"].answer == NO_READ_ANSWER
    assert result["timing"]["hop_count"] == 2


def test_contract_refusal_does_not_consume_backend_correction_attempt(monkeypatch):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node
    from erp_data.orm_agent_helpers import QueryPlan

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    replies = iter([
        AIMessage(content="", tool_calls=[{"name": "search_count", "args": {}, "id": "tc1"}]),
        AIMessage(content="", tool_calls=[{"name": "search_count", "args": {}, "id": "tc2"}]),
        AIMessage(content="", tool_calls=[{"name": "search_count", "args": {}, "id": "tc3"}]),
        AIMessage(content="Il y a 4 tâches.") ,
    ])
    outcomes = iter([
        ("search_count", {}, "Query refused: missing condition_id", False),
        ("search_count", {}, "ORM read refused: invalid selection value", False),
        ("search_count", {}, "4 records", True),
    ])

    plan = QueryPlan(subject="tâches", conditions=["restantes"], result_kind="count", answer_language="français")
    monkeypatch.setattr(node, "_build_llm", lambda **_kwargs: FakeLlm())
    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "invoke_llm", lambda *_args: next(replies))
    monkeypatch.setattr(node, "execute_tool_call", lambda *_args, **_kwargs: next(outcomes))

    result = node._run_react("Combien de tâches restantes ?", [], MagicMock(), "trace", plan=plan, planning_calls=1)

    assert result.answer == "Il y a 4 tâches."
    assert result.hops == 3


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


def test_prompt_does_not_equate_related_display_names_with_business_state():
    assert "champ explicite de type booléen, sélection ou pourcentage" in ORM_AGENT_SYSTEM_PROMPT
    assert "Ne remplace jamais cet état par des noms d'affichage" in ORM_AGENT_SYSTEM_PROMPT


def test_prompt_requires_a_read_for_existence_and_count_questions():
    assert "Une question d'existence ou de comptage" in ORM_AGENT_SYSTEM_PROMPT
    assert "jamais du schéma seul" in ORM_AGENT_SYSTEM_PROMPT


def test_prompt_lists_every_parent_for_a_for_each_question():
    assert "pour chaque X, quels Y" in ORM_AGENT_SYSTEM_PROMPT
    assert "Ne pars pas de Y" in ORM_AGENT_SYSTEM_PROMPT


def test_query_planner_prompt_makes_the_parent_of_a_for_each_question_the_subject(monkeypatch):
    class StructuredPlanner:
        def with_structured_output(self, _schema, method):
            return self

    sent = []
    monkeypatch.setattr(
        "erp_data.orm_agent_helpers.invoke_llm",
        lambda _llm, messages: sent.extend(messages) or QueryPlan(
            subject="commandes", result_kind="list", answer_language="français"
        ),
    )
    plan_orm_question("Pour chaque commande, quels transferts ?", lambda **_kwargs: StructuredPlanner())
    assert "le sujet est X ; Y est la valeur demandée, pas une condition" in sent[0].content


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


@pytest.mark.parametrize(
    ("kind", "tools", "expected"),
    [
        ("aggregate", ["fields_get", "search_count"], True),
        ("aggregate", ["search_count", "read_group"], False),
        ("aggregate", [], False),
        ("count", ["search_count"], False),
    ],
)
def test_counting_rows_does_not_answer_a_question_about_a_total(kind, tools, expected):
    from erp_data.orm_agent_helpers import counted_instead_of_measured

    plan = QueryPlan(subject="dépenses", result_kind=kind, answer_language="English")
    assert counted_instead_of_measured(plan, tools) is expected
    assert counted_instead_of_measured(None, tools) is False


def test_a_count_answer_to_a_total_question_is_sent_back_once_to_read_the_measure(monkeypatch):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node
    from erp_data.prompts import MEASURE_READ_REMINDER

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    replies = iter([
        AIMessage(content="", tool_calls=[{"name": "search_count", "args": {}, "id": "tc1"}]),
        AIMessage(content="Aucune dépense."),
        AIMessage(content="", tool_calls=[{"name": "read_group", "args": {}, "id": "tc2"}]),
        AIMessage(content="Total : 1200."),
    ])
    seen = []

    def fake_invoke(_llm, messages):
        seen.append(messages[-1].content)
        return next(replies)

    def fake_execute(tool_call, _tools, _plan=None):
        _record_read(method=tool_call["name"])
        return tool_call["name"], {}, "observation", True

    plan = QueryPlan(subject="dépenses", result_kind="aggregate", answer_language="English")
    monkeypatch.setattr(node, "plan_orm_question", lambda *_a: (plan, 1))
    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", fake_invoke)
    monkeypatch.setattr(node, "execute_tool_call", fake_execute)
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock())

    result = node.orm_agent_loop({"question": "Combien a-t-on dépensé le mois dernier ?"})
    assert result["response"].answer == "Total : 1200."
    assert seen[2] == MEASURE_READ_REMINDER


@pytest.mark.parametrize(
    ("kind", "tools", "expected"),
    [
        ("count", ["list_models", "fields_get"], True),
        ("list", [], True),
        ("detail", ["fields_get"], True),
        ("count", ["fields_get", "search_count"], False),
        ("detail", ["read"], False),
        ("unknown", ["fields_get"], False),
    ],
)
def test_a_plan_expecting_data_needs_a_record_read(kind, tools, expected):
    from erp_data.orm_agent_helpers import answered_without_reading

    plan = QueryPlan(subject="factures", result_kind=kind, answer_language="English")
    assert answered_without_reading(plan, tools) is expected
    assert answered_without_reading(None, tools) is False


def test_an_answer_without_any_read_is_sent_back_once_to_read(monkeypatch):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node
    from erp_data.prompts import NO_READ_REMINDER

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    replies = iter([
        AIMessage(content="Aucune facture ne peut avoir deux statuts."),
        AIMessage(content="", tool_calls=[{"name": "search_count", "args": {}, "id": "tc1"}]),
        AIMessage(content="Aucune facture."),
    ])
    seen = []

    def fake_invoke(_llm, messages):
        seen.append(messages[-1].content)
        return next(replies)

    def fake_execute(tool_call, _tools, _plan=None):
        _record_read(method=tool_call["name"])
        return tool_call["name"], {}, "observation", True

    plan = QueryPlan(subject="factures", result_kind="count", answer_language="French")
    monkeypatch.setattr(node, "plan_orm_question", lambda *_a: (plan, 1))
    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", fake_invoke)
    monkeypatch.setattr(node, "execute_tool_call", fake_execute)
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock())

    result = node.orm_agent_loop({"question": "Existe-t-il une facture brouillon et publiee ?"})
    assert result["response"].answer == "Aucune facture."
    assert seen[1] == NO_READ_REMINDER
    assert result["timing"]["llm_call_count"] == 4


def test_the_reminder_to_read_is_sent_only_once(monkeypatch):
    from langchain_core.messages import AIMessage

    import erp_data.orm_agent_node as node

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    replies = iter([AIMessage(content="Sur quelle période ?"), AIMessage(content="Précisez la période.")])
    plan = QueryPlan(subject="factures", result_kind="list", answer_language="French")
    monkeypatch.setattr(node, "plan_orm_question", lambda *_a: (plan, 1))
    monkeypatch.setattr(node, "resolve_orm_tools", lambda: [])
    monkeypatch.setattr(node, "_build_llm", lambda **_k: FakeLlm())
    monkeypatch.setattr(node, "invoke_llm", lambda *_a: next(replies))
    monkeypatch.setattr(node, "ReasoningTraceLogger", lambda: MagicMock())

    result = node.orm_agent_loop({"question": "Liste des factures ?"})
    assert result["response"].answer == "Précisez la période."


def test_plan_text_asks_for_the_question_language_with_untranslated_odoo_labels():
    from erp_data.orm_agent_helpers import format_query_plan

    text = format_query_plan(QueryPlan(subject="expenses", result_kind="aggregate", answer_language="English"))
    assert "Langue de la réponse : English" in text
    assert "libellés Odoo non traduits" in text


def test_prompt_forbids_a_currency_that_the_data_does_not_show():
    assert "N'ajoute aucune devise ni unité absente des observations" in ORM_AGENT_SYSTEM_PROMPT


def test_domain_leaves_written_as_strings_are_parsed():
    from erp_data.runtime.langchain_tools import _coerce_domain

    assert _coerce_domain(["['payment_type', '=', 'inbound']"]) == [["payment_type", "=", "inbound"]]
    assert _coerce_domain(["('state', '=', 'posted')"]) == [["state", "=", "posted"]]
    assert _coerce_domain(["[('move_type', '=', 'in_invoice'), ('state', '=', 'posted')]"]) == [
        ("move_type", "=", "in_invoice"), ("state", "=", "posted"),
    ]
    assert _coerce_domain(["|", ["a", "=", 1], "['b', '=', 2]"]) == ["|", ["a", "=", 1], ["b", "=", 2]]


def test_fields_get_exposes_the_currency_field_and_the_prompt_uses_it():
    from erp_data.odoo_connector import FIELD_ATTRIBUTES

    assert "currency_field" in FIELD_ATTRIBUTES
    assert "currency_field" in ORM_AGENT_SYSTEM_PROMPT
    assert "n'est pas stocké" in ORM_AGENT_SYSTEM_PROMPT
    assert "plusieurs sortes d'enregistrements" in ORM_AGENT_SYSTEM_PROMPT
