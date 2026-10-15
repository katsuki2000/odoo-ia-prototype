"""
code_intelligence/tests/test_s2_0_business_resolver.py

Unit tests for Business Term Resolver.
Tests static alias lookup, graph model matching, and unresolved concept fallback.
"""

import unicodedata

import pytest
import networkx as nx
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.agent.resolution.alias_targets import alias_targets_in_graph


@pytest.fixture
def mock_graph():
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node("model:custom_credit_note_approval", node_type="Model", name="custom_credit_note_approval")
    G.add_node("model:custom_purchase_request", node_type="Model", name="custom_purchase_request")
    G.add_node("model:custom.purchase.request", node_type="Model", name="custom.purchase.request")
    G.add_node("model:custom_asset_loan", node_type="Model", name="custom_asset_loan")
    G.add_node("model:custom.asset.loan", node_type="Model", name="custom.asset.loan")
    G.add_node("model:hr.leave", node_type="Model", name="hr.leave")
    G.add_node("model:custom.reimbursement.request", node_type="Model", name="custom.reimbursement.request")
    G.add_node("module:custom_expense_reimbursement_indirect", node_type="Module", name="custom_expense_reimbursement_indirect")
    G.add_edge("model:custom.reimbursement.request", "module:custom_expense_reimbursement_indirect", edge_type="DEFINED_IN")

    # regression fixture: a Field labeled exactly "avoirs" on an unrelated
    # model (res.partner), mirroring the real bug observed in production
    # ('avoirs' -> fuzzy: res.partner (100.0)). Without this node, the
    # fuzzy index is empty and the ordering bug can never be exercised —
    # the test would pass even if someone reverted the fix.
    G.add_node("model:res.partner", node_type="Model", name="res.partner")
    G.add_node(
        "field:res_partner_avoirs",
        node_type="Field",
        label="avoirs",
        model="res.partner",
    )
    return G


def test_s2_0_static_alias_credit_note(mock_graph):
    res = resolve_business_term("Qui a le permission d'approuver un avoir de 25 000€ ?", mock_graph, use_static_aliases=True)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "account.move" in res.resolved_models or "custom_credit_note_approval" in res.resolved_models


def test_s2_0_static_alias_purchase_request(mock_graph):
    res = resolve_business_term("Qui peut valider une demande d'achat de 15000€ ?", mock_graph, use_static_aliases=True)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "custom.purchase.request" in res.resolved_models


def test_s2_0_static_alias_purchase_request_does_not_bundle_purchase_order(mock_graph):
    """ gap (2026-08-10, module 4/8, /04c): 'demande d'achat'
    used to also resolve to the real, unrelated standard Odoo 'purchase.order'
    model, which drowned out custom.purchase.request's own 10 000e threshold
    fact under the forced-dispatch hop budget .
    'demande d'achat' is the literal _description of custom.purchase.request
    itself -- an unambiguous match, not a case needing a second candidate."""
    res = resolve_business_term("Qui peut valider une demande d'achat de 15000€ ?", mock_graph, use_static_aliases=True)
    assert "purchase.order" not in res.resolved_models


def test_s2_0_static_alias_asset_loan(mock_graph):
    res = resolve_business_term("Comment faire une demande de mise à disposition de matériel ?", mock_graph, use_static_aliases=True)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "custom.asset.loan" in res.resolved_models


def test_s2_0_static_alias_expense(mock_graph):
    res = resolve_business_term("Qui valide la note de frais dans custom_expense_reimbursement_indirect ?", mock_graph, use_static_aliases=True)
    assert res.is_resolved is True
    assert res.source_step in ("static_alias", "exact_technical_mention")
    assert "custom.reimbursement.request" in res.resolved_models


def test_s2_0_unresolved_concept(mock_graph):
    res = resolve_business_term("Quelle est la météo à Paris aujourd'hui ?", mock_graph, use_static_aliases=True)
    assert res.is_resolved is False
    assert res.source_step == "unresolved"
    assert res.confidence == 0.0


def test_s2_0_alias_not_shadowed_by_fuzzy_single_token(mock_graph):
    """
    Regression test for Bug #1 (): a short/single-token query matching
    a static alias must resolve via static_alias, never be shadowed by a
    same-score fuzzy match on an unrelated model's Field label.

    Prior to the fix, fuzzy matching ran BEFORE the static alias lookup,
    and a 1-token query against a 1-token label produced
    length_penalty = min(1/1, 1.0) ** 0.5 = 1.0 (no penalty at all),
    letting 'avoirs' resolve to res.partner (100.0) instead of the
    correct account.move alias.
    """
    res = resolve_business_term("avoirs", mock_graph, use_static_aliases=True)
    assert res.source_step == "static_alias"
    assert res.resolved_models == ["account.move"]
    assert "res.partner" not in res.resolved_models


def test_s2_0_alias_word_boundary_respects_token_order(mock_graph):
    """
    Regression test: multi-word aliases must not match on token presence
    alone, regardless of order. 'disposition à mise' contains the same
    words as the 'mise à disposition' alias but in reversed order and
    must NOT resolve via static_alias.
    """
    res = resolve_business_term("disposition à mise", mock_graph, use_static_aliases=True)
    assert res.source_step != "static_alias"


def test_s2_0_alias_matches_nfd_decomposed_input(mock_graph):
    """
    Defensive test: a query typed/copy-pasted with NFD-decomposed accents
    (e.g. 'a' + combining grave accent U+0300, visually identical to 'à')
    must still match the NFC-stored alias table. Guards against the
    Unicode-form mismatch class of bug even though it was not reproduced
    in this specific alias table.
    """
    nfd_query = unicodedata.normalize("NFD", "mise à disposition de matériel")
    assert nfd_query != "mise à disposition de matériel"  # sanity check: genuinely different bytes
    res = resolve_business_term(nfd_query, mock_graph, use_static_aliases=True)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "custom.asset.loan" in res.resolved_models


# --- Bounded LLM Arbitration Tests ------------------------------------

class _FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, reply: str):
        self._reply = reply

    def invoke(self, messages):
        return _FakeLLMResponse(self._reply)


@pytest.fixture
def ambiguous_graph():
    """Two Field labels with near-identical fuzzy scores against the same
    query, mirroring the real 'purchase order approval' case.

    Section 1064: the deterministic tiebreak now only breaks a tie on a
    model-name segment that is RARE across the graph's own model population
    (same discipline as matching.py's rare-token evidence, Section 1040) --
    on the real 535-model graph 'order' alone names 10 models, so it cannot
    discriminate between two tied candidates that both plausibly fit. A
    2-model graph makes every segment trivially 'rare' (floor of 3 owners)
    and would let 'order' decide the tie by fixture accident rather than by
    genuine signal, defeating the point of this fixture -- a handful of
    unrelated '.order'-bearing models restores that realistic rarity so the
    scenario stays genuinely ambiguous and reaches LLM arbitration, exactly
    as the real production case does.
    """
    G = nx.DiGraph()
    G.add_node("model:custom.purchase.request", node_type="Model", name="custom.purchase.request")
    G.add_node("model:purchase.order.line", node_type="Model", name="purchase.order.line")
    G.add_node("field:f1", node_type="Field", label="purchase order approval request", model="custom.purchase.request")
    G.add_node("field:f2", node_type="Field", label="purchase order line approval", model="purchase.order.line")
    for extra in ("sale.order", "pos.order", "repair.order", "mrp.production.order"):
        G.add_node(f"model:{extra}", node_type="Model", name=extra)
    return G


def test_s2_0_llm_arbitration_picks_valid_candidate(ambiguous_graph):
    fake_llm = _FakeLLM(reply="custom.purchase.request")
    res = resolve_business_term("purchase order approval", ambiguous_graph, llm=fake_llm)
    assert res.source_step == "llm_arbitration"
    assert res.resolved_models == ["custom.purchase.request"]
    assert res.confidence == 0.6


def test_s2_0_llm_arbitration_rejects_out_of_list_hallucination(ambiguous_graph):
    fake_llm = _FakeLLM(reply="account.move")  # not in the closed candidate list
    res = resolve_business_term("purchase order approval", ambiguous_graph, llm=fake_llm)
    assert res.source_step == "unresolved"
    assert res.is_resolved is False


def test_s2_0_llm_arbitration_none_response_falls_back_unresolved(ambiguous_graph):
    fake_llm = _FakeLLM(reply="NONE")
    res = resolve_business_term("purchase order approval", ambiguous_graph, llm=fake_llm)
    assert res.source_step == "unresolved"


def test_s2_0_no_llm_call_when_top_candidate_is_clear(mock_graph):
    """Clear alias/fuzzy resolution must never trigger LLM arbitration."""
    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("LLM should not be invoked when resolution is unambiguous")

    fake_llm = type("Blocker", (), {"invoke": _should_not_be_called})()
    res = resolve_business_term("avoirs", mock_graph, llm=fake_llm, use_static_aliases=True)
    assert res.source_step == "static_alias"

def _graph_with_models(*models):
    graph = nx.DiGraph()
    for model in models:
        graph.add_node(f"model:{model}", node_type="Model", name=model)
    return graph


def test_alias_to_models_absent_from_loaded_graph_is_not_resolved():
    graph = _graph_with_models("purchase.order", "account.move")

    result = resolve_business_term("comment je fais une demande d'achat sur l'ERP?", graph, use_static_aliases=True)

    assert result.source_step != "static_alias"
    assert "purchase.request" not in result.resolved_models
    assert "custom.purchase.request" not in result.resolved_models


def test_absent_alias_is_left_out_of_the_resolved_terms():
    graph = _graph_with_models("purchase.order")

    result = resolve_business_term("demande d'achat et commande d'achat", graph, use_static_aliases=True)

    assert result.source_step == "static_alias"
    assert result.resolved_models == ["purchase.order"]
    assert "demande d'achat" not in result.user_term.split(", ")


def test_alias_targets_are_kept_when_no_graph_is_loaded():
    result = resolve_business_term("demande d'achat", None, use_static_aliases=True)

    assert result.source_step == "static_alias"
    assert result.resolved_models == ["purchase.request", "custom.purchase.request"]


def test_alias_targets_are_kept_when_graph_is_empty():
    result = resolve_business_term("demande d'achat", nx.DiGraph(), use_static_aliases=True)

    assert result.source_step == "static_alias"
    assert result.resolved_models == ["purchase.request", "custom.purchase.request"]


def test_exact_mention_merge_drops_alias_targets_absent_from_graph():
    graph = _graph_with_models("sale.order", "purchase.order")

    result = resolve_business_term("quel est le workflow de sale.order pour une demande d'achat ?", graph, use_static_aliases=True)

    assert result.source_step == "exact_technical_mention"
    assert result.resolved_models == ["sale.order"]


def test_exact_mention_merge_keeps_alias_targets_present_in_graph():
    graph = _graph_with_models("sale.order", "purchase.order")

    result = resolve_business_term("workflow de sale.order et d'une commande d'achat", graph, use_static_aliases=True)

    assert result.source_step == "exact_technical_mention"
    assert result.resolved_models == ["sale.order", "purchase.order"]


def test_alias_targets_prefer_custom_when_both_alternatives_exist():
    graph = _graph_with_models("purchase.request", "custom.purchase.request")

    targets = alias_targets_in_graph(graph, ["purchase.request", "custom.purchase.request"])

    assert targets == ["custom.purchase.request"]


def test_alias_targets_fall_back_to_the_native_alternative():
    graph = _graph_with_models("purchase.request")

    targets = alias_targets_in_graph(graph, ["purchase.request", "custom.purchase.request"])

    assert targets == ["purchase.request"]


def test_alias_targets_keep_modules_and_drop_unknown_names():
    graph = _graph_with_models("sale.order")
    graph.add_node("module:sale", node_type="Module", name="sale")

    assert alias_targets_in_graph(graph, ["sale", "sale.order", "sale.unknown"]) == ["sale", "sale.order"]
    assert alias_targets_in_graph(graph, ["purchase.request"]) == []
