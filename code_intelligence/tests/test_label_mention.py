import networkx as nx
import pytest

from code_intelligence.agent.resolution import resolver
from code_intelligence.agent.resolution.dense_lookup import DenseResolution
from code_intelligence.agent.resolution.label_mention import quoted_model_labels
from code_intelligence.agent.resolution.resolver import resolve_business_term


def _add_model(graph, name, *labels):
    graph.add_node(
        f"model:{name}", node_type="Model", name=name,
        business_labels=[{"label": label, "language": "fr"} for label in labels],
    )


@pytest.fixture
def graph():
    graph = nx.DiGraph()
    _add_model(graph, "purchase.order", "Purchase Order", "Bon de commande")
    _add_model(graph, "purchase.order.line", "Purchase Order Line")
    _add_model(graph, "sale.order", "Sales Order", "Order")
    _add_model(graph, "res.users", "User")
    _add_model(graph, "hr.employee", "Employee Record")
    _add_model(graph, "hr.contract", "Employee Record")
    return graph


def _capture_arbiter(monkeypatch, models=()):
    from code_intelligence.agent.resolution import fuzzy_lookup
    from code_intelligence.agent.resolution.arbitration import ARBITRATION_SELECTED, ArbitrationTrace

    seen = {}

    def arbiter(query, candidates, llm, contexts=None):
        seen["candidates"], seen["contexts"] = list(candidates), contexts
        return ArbitrationTrace(None, ARBITRATION_SELECTED, "", tuple(models))

    monkeypatch.setattr(fuzzy_lookup, "_llm_arbitrate", arbiter)
    monkeypatch.setattr(resolver, "resolve_dense_retrieval", lambda *a, **k: DenseResolution(None, ()))
    return seen


def test_single_multiword_label_is_quoted_evidence(graph):
    assert quoted_model_labels("qui peut valider un purchase order ?", graph) == {"purchase.order": "purchase order"}


def test_single_word_label_is_not_evidence(graph):
    assert quoted_model_labels("quel utilisateur a le groupe user ?", graph) == {}
    assert quoted_model_labels("quel order est confirme ?", graph) == {}


def test_label_shared_by_two_models_gives_both(graph):
    assert set(quoted_model_labels("que contient un employee record ?", graph)) == {"hr.employee", "hr.contract"}


def test_longer_label_subsumes_the_shorter_one(graph):
    assert quoted_model_labels("les champs de purchase order line", graph) == {"purchase.order.line": "purchase order line"}


def test_two_distinct_labels_give_both_models(graph):
    assert set(quoted_model_labels("purchase order ou sales order ?", graph)) == {"purchase.order", "sale.order"}


def test_partial_word_is_not_a_mention(graph):
    assert quoted_model_labels("repurchase orders", graph) == {}


def test_case_and_composed_accents_are_normalized():
    graph = nx.DiGraph()
    _add_model(graph, "account.move", "Pi\u00e8ce comptable")
    assert set(quoted_model_labels("une pie\u0300ce COMPTABLE postee", graph)) == {"account.move"}


def test_no_graph_or_no_label_gives_no_evidence():
    assert quoted_model_labels("purchase order", None) == {}
    assert quoted_model_labels("purchase order", nx.DiGraph()) == {}


def test_technical_name_wins_over_label(graph):
    concept = resolve_business_term("purchase order sur sale.order", graph)
    assert concept.source_step == "exact_technical_mention"
    assert concept.resolved_models == ["sale.order"]


def test_quoted_models_lead_the_closed_list_with_annotated_context(graph, monkeypatch):
    seen = _capture_arbiter(monkeypatch)
    resolve_business_term("Comment confirmer un Purchase Order ?", graph, llm=object())
    assert seen["candidates"][0] == "purchase.order"
    assert "quoted in the question: purchase order" in seen["contexts"]["purchase.order"]


def test_question_with_two_quoted_subjects_is_left_to_the_arbiter(graph, monkeypatch):
    seen = _capture_arbiter(monkeypatch, models=("purchase.order", "sale.order"))
    concept = resolve_business_term("purchase order ou sales order ?", graph, llm=object())
    assert set(seen["candidates"][:2]) == {"purchase.order", "sale.order"}
    assert concept.resolved_models == ["purchase.order", "sale.order"]


def test_field_and_label_pair_takes_precedence_over_a_generic_label():
    graph = nx.DiGraph()
    _add_model(graph, "maintenance.equipment", "Equipement de maintenance")
    graph.add_node("field:maintenance.equipment.cost", node_type="Field", model="maintenance.equipment", name="cost", label="Cost")
    _add_model(graph, "ir.model.access", "Acces en lecture")
    question = "pourquoi le champ 'cost' d'un equipement n'est-il pas visible avec acces en lecture ?"
    assert quoted_model_labels(question, graph) == {}


def test_arbiter_prompt_explains_the_quoted_label_marker():
    from code_intelligence.agent.resolution.arbitration import _ARBITRATION_SYSTEM_PROMPT, QUOTED_LABEL_MARKER

    assert QUOTED_LABEL_MARKER in _ARBITRATION_SYSTEM_PROMPT
