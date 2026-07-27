"""
code_intelligence/tests/test_s2_0_business_resolver.py

Unit tests for Story S2.0: Business Term Resolver.
Tests static alias lookup, graph model matching, and unresolved concept fallback.
"""

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
