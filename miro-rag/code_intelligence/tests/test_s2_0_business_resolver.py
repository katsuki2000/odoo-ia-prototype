"""
code_intelligence/tests/test_s2_0_business_resolver.py

Unit tests for Story S2.0: Business Term Resolver.
Tests static alias lookup, graph model matching, and unresolved concept fallback.
"""

import unicodedata

import pytest
import networkx as nx
from code_intelligence.business_resolver import resolve_business_term, BUSINESS_ALIASES


@pytest.fixture
def mock_graph():
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node("model:custom_credit_note_approval", node_type="Model", name="custom_credit_note_approval")
    G.add_node("model:custom_purchase_request", node_type="Model", name="custom_purchase_request")
    G.add_node("model:custom_asset_loan", node_type="Model", name="custom_asset_loan")
    G.add_node("model:hr.leave", node_type="Model", name="hr.leave")
    G.add_node("module:custom_expense_reimbursement_indirect", node_type="Module", name="custom_expense_reimbursement_indirect")

    # J1 regression fixture: a Field labeled exactly "avoirs" on an unrelated
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
    res = resolve_business_term("Qui a le droit d'approuver un avoir de 25 000€ ?", mock_graph)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "account.move" in res.resolved_models or "custom_credit_note_approval" in res.resolved_models


def test_s2_0_static_alias_purchase_request(mock_graph):
    res = resolve_business_term("Qui peut valider une demande d'achat de 15000€ ?", mock_graph)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "custom.purchase.request" in res.resolved_models


def test_s2_0_static_alias_purchase_request_does_not_bundle_purchase_order(mock_graph):
    """Bloc 9 gap (2026-08-10, module 4/8, bloc9-04a/04c): 'demande d'achat'
    used to also resolve to the real, unrelated standard Odoo 'purchase.order'
    model, which drowned out custom.purchase.request's own 10 000e threshold
    fact under the forced-dispatch hop budget (see contexte.txt section 21).
    'demande d'achat' is the literal _description of custom.purchase.request
    itself -- an unambiguous match, not a case needing a second candidate."""
    res = resolve_business_term("Qui peut valider une demande d'achat de 15000€ ?", mock_graph)
    assert "purchase.order" not in res.resolved_models


def test_s2_0_static_alias_asset_loan(mock_graph):
    res = resolve_business_term("Comment faire une demande de mise à disposition de matériel ?", mock_graph)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "custom.asset.loan" in res.resolved_models


def test_s2_0_static_alias_expense(mock_graph):
    res = resolve_business_term("Qui valide la note de frais dans custom_expense_reimbursement_indirect ?", mock_graph)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "custom.reimbursement.request" in res.resolved_models


def test_s2_0_unresolved_concept(mock_graph):
    res = resolve_business_term("Quelle est la météo à Paris aujourd'hui ?", mock_graph)
    assert res.is_resolved is False
    assert res.source_step == "unresolved"
    assert res.confidence == 0.0


def test_s2_0_alias_not_shadowed_by_fuzzy_single_token(mock_graph):
    """
    Regression test for Bug #1 (J1): a short/single-token query matching
    a static alias must resolve via static_alias, never be shadowed by a
    same-score fuzzy match on an unrelated model's Field label.

    Prior to the fix, fuzzy matching ran BEFORE the static alias lookup,
    and a 1-token query against a 1-token label produced
    length_penalty = min(1/1, 1.0) ** 0.5 = 1.0 (no penalty at all),
    letting 'avoirs' resolve to res.partner (100.0) instead of the
    correct account.move alias.
    """
    res = resolve_business_term("avoirs", mock_graph)
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
    res = resolve_business_term("disposition à mise", mock_graph)
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
    res = resolve_business_term(nfd_query, mock_graph)
    assert res.is_resolved is True
    assert res.source_step == "static_alias"
    assert "custom.asset.loan" in res.resolved_models


# --- J2: Bounded LLM Arbitration Tests ------------------------------------

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
    query, mirroring the real 'purchase order approval' case."""
    G = nx.DiGraph()
    G.add_node("model:custom.purchase.request", node_type="Model", name="custom.purchase.request")
    G.add_node("model:purchase.order.line", node_type="Model", name="purchase.order.line")
    G.add_node("field:f1", node_type="Field", label="purchase order approval request", model="custom.purchase.request")
    G.add_node("field:f2", node_type="Field", label="purchase order line approval", model="purchase.order.line")
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
    res = resolve_business_term("avoirs", mock_graph, llm=fake_llm)
    assert res.source_step == "static_alias"