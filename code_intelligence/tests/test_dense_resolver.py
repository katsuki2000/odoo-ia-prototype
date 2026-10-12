"""Tests for the dense retrieval resolution step (Option A: alias-free resolver)."""

import pytest

from code_intelligence.agent.matching import ResolvedConcept
from code_intelligence.agent.resolution.dense_lookup import (
    DENSE_MIN_SCORE,
    DENSE_SCORE_GAP_THRESHOLD,
    resolve_dense_retrieval,
)


def _fake_scored_retrieval(results, status=None):
    """Patch retrieve_semantic_model_candidates_scored to return fixed results."""
    from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus

    actual_status = status or (
        SemanticRetrievalStatus.SUCCESS if results else SemanticRetrievalStatus.NO_CANDIDATES
    )
    return results, actual_status


class TestDenseResolution:
    def test_clear_winner_resolves(self, monkeypatch):
        scored = [("purchase.order", 0.56), ("sale.order", 0.30)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("bon de commande fournisseur", G, "fr_FR")
        assert result is not None
        assert result.is_resolved
        assert result.resolved_models == ["purchase.order"]
        assert result.source_step == "dense_retrieval"
        assert result.confidence == 0.56

    def test_ambiguous_scores_fall_through(self, monkeypatch):
        scored = [("purchase.order", 0.50), ("sale.order", 0.48)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("confirmer une commande", G, "fr_FR")
        assert result is None

    def test_low_score_falls_through(self, monkeypatch):
        scored = [("res.partner", 0.15)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("inventaire galactique", G, "fr_FR")
        assert result is None

    def test_disabled_falls_through(self, monkeypatch):
        from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: ([], SemanticRetrievalStatus.DISABLED),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("purchase order", G, "en_US")
        assert result is None

    def test_error_falls_through(self, monkeypatch):
        from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: ([], SemanticRetrievalStatus.ERROR),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("purchase order", G, "en_US")
        assert result is None

    def test_no_graph_returns_none(self):
        result = resolve_dense_retrieval("purchase order", None, "en_US")
        assert result is None

    def test_empty_results_falls_through(self, monkeypatch):
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval([]),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("xyz", G, "fr_FR")
        assert result is None

    def test_sole_candidate_above_threshold_resolves(self, monkeypatch):
        scored = [("hr.leave", 0.45)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("demande de conge", G, "fr_FR")
        assert result is not None
        assert result.resolved_models == ["hr.leave"]
        assert "sole candidate" in result.reason


class TestResolverDefaultChanged:
    """Verify that the production resolver no longer uses static aliases by default."""

    def test_default_skips_alias(self):
        from code_intelligence.agent.resolver import resolve_business_term
        import inspect
        sig = inspect.signature(resolve_business_term)
        assert sig.parameters["use_static_aliases"].default is False

    def test_aliases_still_available_when_requested(self):
        from code_intelligence.agent.resolver import resolve_business_term
        import networkx as nx
        G = nx.DiGraph()
        G.add_node("model:account.move", node_type="Model", name="account.move")
        result = resolve_business_term("avoir", G, llm=None, use_static_aliases=True)
        assert result.is_resolved
        assert "account.move" in result.resolved_models
