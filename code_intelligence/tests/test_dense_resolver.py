"""Tests for the dense retrieval resolution step (Option A: alias-free resolver)."""

import pytest

from code_intelligence.agent.resolution.dense_lookup import (
    DenseResolution,
    resolve_dense_retrieval,
)
from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus


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
        result = resolve_dense_retrieval("bon de commande fournisseur", G, "fr_FR").concept
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
        result = resolve_dense_retrieval("confirmer une commande", G, "fr_FR").concept
        assert result is None

    def test_low_score_falls_through(self, monkeypatch):
        scored = [("res.partner", 0.15)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("inventaire galactique", G, "fr_FR").concept
        assert result is None

    def test_disabled_falls_through(self, monkeypatch):
        from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: ([], SemanticRetrievalStatus.DISABLED),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("purchase order", G, "en_US").concept
        assert result is None

    def test_error_falls_through(self, monkeypatch):
        from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: ([], SemanticRetrievalStatus.ERROR),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("purchase order", G, "en_US").concept
        assert result is None

    def test_no_graph_returns_none(self):
        result = resolve_dense_retrieval("purchase order", None, "en_US").concept
        assert result is None

    def test_empty_results_falls_through(self, monkeypatch):
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval([]),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("xyz", G, "fr_FR").concept
        assert result is None

    def test_sole_candidate_above_threshold_resolves(self, monkeypatch):
        scored = [("hr.leave", 0.45)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("demande de conge", G, "fr_FR").concept
        assert result is not None
        assert result.resolved_models == ["hr.leave"]
        assert "sole candidate" in result.reason


class TestDenseStatusVisibility:
    """The dense outcome must reach the resolved concept, whatever the fall-through reason."""

    @pytest.mark.parametrize(
        "status", [SemanticRetrievalStatus.DISABLED, SemanticRetrievalStatus.ERROR],
    )
    def test_unavailable_status_is_reported(self, monkeypatch, status):
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: ([], status),
        )
        import networkx as nx
        outcome = resolve_dense_retrieval("purchase order", nx.DiGraph(), "en_US")
        assert outcome == DenseResolution(None, status)

    def test_ambiguous_fall_through_keeps_success_status(self, monkeypatch):
        scored = [("purchase.order", 0.50), ("sale.order", 0.48)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        outcome = resolve_dense_retrieval("confirmer une commande", nx.DiGraph(), "fr_FR")
        assert outcome == DenseResolution(None, SemanticRetrievalStatus.SUCCESS)

    def test_step_not_run_without_graph(self):
        assert resolve_dense_retrieval("purchase order", None, "en_US") == DenseResolution(None, None)

    @pytest.mark.parametrize(
        "status", [SemanticRetrievalStatus.DISABLED, SemanticRetrievalStatus.ERROR],
    )
    def test_resolver_publishes_dense_outage_on_unresolved_concept(self, monkeypatch, status):
        from code_intelligence.agent import resolver
        import networkx as nx
        monkeypatch.setattr(
            resolver, "resolve_dense_retrieval", lambda *a, **kw: DenseResolution(None, status),
        )
        result = resolver.resolve_business_term("comment valider ?", nx.DiGraph(), llm=None)
        assert not result.is_resolved
        assert result.diagnostics == {"semantic_retrieval": status.value}

    def test_resolver_omits_dense_status_when_step_not_run(self, monkeypatch):
        from code_intelligence.agent import resolver
        import networkx as nx
        monkeypatch.setattr(
            resolver, "resolve_dense_retrieval", lambda *a, **kw: DenseResolution(None, None),
        )
        result = resolver.resolve_business_term("comment valider ?", nx.DiGraph(), llm=None)
        assert result.diagnostics == {}


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
