"""
code_intelligence/tests/test_s2_8_fidelity_checker.py

Unit tests for Story S2.8: Fidelity Checker & Anti-Hallucination Guard.
Ensures that querying unknown/absent models or symbols explicitly returns an
'absent from corpus' status message instead of fallbacks or hallucinated answers.
"""

import pytest
import networkx as nx
from code_intelligence.ci_agent_tools import (
    set_graph_ref,
    qui_a_acces_a,
    evaluer_regles_enregistrement,
    analyser_actions_serveur,
    analyser_verrous_securite,
)


@pytest.fixture
def sample_graph():
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order", filepaths=["/addons/sale/models/sale_order.py"])
    set_graph_ref(G)
    return G


class TestFidelityChecker:
    def test_unknown_model_access_query(self, sample_graph):
        res = qui_a_acces_a.invoke({"model_name": "non_existent_model"})
        assert "non_existent_model" in res
        assert "not found in the indexed knowledge graph" in res or "absent du corpus" in res.lower()

    def test_unknown_model_record_rules(self, sample_graph):
        res = evaluer_regles_enregistrement.invoke({"model_name": "unknown.model"})
        assert "unknown.model" in res
        assert "not found" in res.lower() or "absent" in res.lower()

    def test_unknown_model_server_actions(self, sample_graph):
        res = analyser_actions_serveur.invoke({"model_name": "ghost.model"})
        assert "ghost.model" in res
        assert "not found" in res.lower() or "absent" in res.lower()

    def test_unknown_model_security_locks(self, sample_graph):
        res = analyser_verrous_securite.invoke({"model_name": "fake.model"})
        assert "fake.model" in res
        assert "not found" in res.lower() or "absent" in res.lower()
