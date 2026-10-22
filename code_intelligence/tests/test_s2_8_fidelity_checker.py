"""
code_intelligence/tests/test_s2_8_fidelity_checker.py

Unit tests for Fidelity Checker & Anti-Hallucination Guard.
Ensures that querying unknown/absent models or symbols explicitly returns an
'absent from corpus' status message instead of fallbacks or hallucinated answers.
"""

import pytest
import networkx as nx
from code_intelligence.agent.tools import (
    who_has_access_to,
    evaluate_record_rules,
    analyze_server_actions,
    analyze_security_locks,
)
from code_intelligence.agent.tools.helpers import set_graph_ref


@pytest.fixture
def sample_graph():
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order", filepaths=["/addons/sale/models/sale_order.py"])
    set_graph_ref(G)
    return G


class TestFidelityChecker:
    def test_unknown_model_access_query(self, sample_graph):
        res = who_has_access_to.invoke({"model_name": "non_existent_model"})
        assert "non_existent_model" in res
        assert "not found in the indexed knowledge graph" in res or "absent du corpus" in res.lower()

    def test_unknown_model_record_rules(self, sample_graph):
        res = evaluate_record_rules.invoke({"model_name": "unknown.model"})
        assert "unknown.model" in res
        assert "not found" in res.lower() or "absent" in res.lower()

    def test_unknown_model_server_actions(self, sample_graph):
        res = analyze_server_actions.invoke({"model_name": "ghost.model"})
        assert "ghost.model" in res
        assert "not found" in res.lower() or "absent" in res.lower()

    def test_unknown_model_security_locks(self, sample_graph):
        res = analyze_security_locks.invoke({"model_name": "fake.model"})
        assert "fake.model" in res
        assert "not found" in res.lower() or "absent" in res.lower()
