"""
code_intelligence/tests/test_bloc_b1_evidence_list_involved_modules.py

B1 (todo/contexte.txt section 460+, tool 9/24): unit tests for the
structured Evidence produced by list_involved_modules_with_evidence()
(Option C, same arbitrage as analyze_method_override_chain, section 456).
list_involved_modules_with_role() itself (the pre-existing List[Tuple]
contract used by ci_agent_tools.py's list_involved_modules tool) is
deliberately NOT touched by this file -- every test here cross-checks that
its output is identical to InvolvedModulesResult.modules, so a regression
on the public contract would fail loudly here too.

Evidence shape covered:
  - model absent from the graph: 1 explicit negative fact, HIGH.
  - model present but no real DEFINED_IN edge: 1 explicit negative fact,
    HIGH -- same fact as the "absent" case (the ['base', 'unknown']
    display fallback is never asserted as Evidence, only used for
    .modules).
  - one Evidence per real DEFINED_IN edge (HIGH, structural/graph-derived),
    value is the role ('declares'/'extends').
  - non-DEFINED_IN or non-module edges are ignored.
"""

import networkx as nx

from code_intelligence.agent.tools.introspection import (
    list_involved_modules_with_role,
    list_involved_modules_with_evidence,
)


class TestInvolvedModulesEvidenceModelAbsent:
    def test_model_absent_single_explicit_negative_fact(self):
        G = nx.DiGraph()
        result = list_involved_modules_with_evidence(G, "account.move")
        assert len(result.evidence) == 1
        ev = result.evidence[0]
        assert ev.confidence == "HIGH"
        assert ev.value == 0
        assert "model not found" in ev.claim
        assert ev.source == "involved_modules:account.move:no_edges"

    def test_modules_matches_public_function(self):
        G = nx.DiGraph()
        modules = list_involved_modules_with_role(G, "account.move")
        result = list_involved_modules_with_evidence(G, "account.move")
        assert result.modules == modules
        assert result.modules == []


class TestInvolvedModulesEvidenceNoRealEdge:
    def test_fallback_never_asserted_as_evidence(self):
        G = nx.DiGraph()
        G.add_node("model:custom.thing", node_type="Model")
        result = list_involved_modules_with_evidence(G, "custom.thing")
        assert len(result.evidence) == 1
        ev = result.evidence[0]
        assert ev.confidence == "HIGH"
        assert ev.value == 0
        assert "base" not in ev.claim
        assert "unknown" not in ev.claim

    def test_modules_still_carries_display_fallback(self):
        G = nx.DiGraph()
        G.add_node("model:custom.thing", node_type="Model")
        modules = list_involved_modules_with_role(G, "custom.thing")
        result = list_involved_modules_with_evidence(G, "custom.thing")
        assert modules == [("base", "unknown")]
        assert result.modules == modules

    def test_irrelevant_edge_types_ignored(self):
        G = nx.DiGraph()
        G.add_node("model:account.move", node_type="Model")
        G.add_node("model:res.partner", node_type="Model")
        G.add_edge("model:account.move", "model:res.partner", edge_type="EXTENDS")
        result = list_involved_modules_with_evidence(G, "account.move")
        assert result.modules == [("base", "unknown")]
        assert len(result.evidence) == 1


class TestInvolvedModulesEvidenceRealEdges:
    def _graph_two_modules(self):
        G = nx.DiGraph()
        G.add_node("model:account.move", node_type="Model")
        G.add_node("module:custom_credit_note", node_type="Module")
        G.add_node("module:custom_credit_note_regional", node_type="Module")
        G.add_edge(
            "model:account.move", "module:custom_credit_note",
            edge_type="DEFINED_IN", role="declares",
        )
        G.add_edge(
            "model:account.move", "module:custom_credit_note_regional",
            edge_type="DEFINED_IN", role="extends",
        )
        return G

    def test_one_evidence_per_module_with_correct_role(self):
        G = self._graph_two_modules()
        result = list_involved_modules_with_evidence(G, "account.move")
        assert len(result.evidence) == 2
        by_source = {e.source: e for e in result.evidence}

        declares_ev = by_source["involved_modules:account.move:custom_credit_note"]
        assert declares_ev.value == "declares"
        assert declares_ev.confidence == "HIGH"
        assert "declares model 'account.move'" in declares_ev.claim

        extends_ev = by_source["involved_modules:account.move:custom_credit_note_regional"]
        assert extends_ev.value == "extends"
        assert extends_ev.confidence == "HIGH"
        assert "extends model 'account.move'" in extends_ev.claim

    def test_modules_matches_public_function(self):
        G = self._graph_two_modules()
        modules = list_involved_modules_with_role(G, "account.move")
        result = list_involved_modules_with_evidence(G, "account.move")
        assert result.modules == modules
        assert result.modules == [
            ("custom_credit_note", "declares"),
            ("custom_credit_note_regional", "extends"),
        ]

    def test_single_declaring_module(self):
        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model")
        G.add_node("module:sale", node_type="Module")
        G.add_edge(
            "model:sale.order", "module:sale",
            edge_type="DEFINED_IN", role="declares",
        )
        result = list_involved_modules_with_evidence(G, "sale.order")
        assert len(result.evidence) == 1
        assert result.evidence[0].value == "declares"
        assert result.modules == [("sale", "declares")]


class TestInvolvedModulesEvidenceDeterminism:
    def test_evidence_id_stable_across_calls(self):
        G = nx.DiGraph()
        G.add_node("model:account.move", node_type="Model")
        G.add_node("module:custom_credit_note", node_type="Module")
        G.add_edge(
            "model:account.move", "module:custom_credit_note",
            edge_type="DEFINED_IN", role="declares",
        )
        r1 = list_involved_modules_with_evidence(G, "account.move")
        r2 = list_involved_modules_with_evidence(G, "account.move")
        ids1 = sorted(e.evidence_id for e in r1.evidence)
        ids2 = sorted(e.evidence_id for e in r2.evidence)
        assert ids1 == ids2
