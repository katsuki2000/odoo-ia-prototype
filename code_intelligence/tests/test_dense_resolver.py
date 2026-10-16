"""Tests that dense retrieval supplies candidates without resolving them."""

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
    def test_clear_semantic_winner_only_proposes_candidates(self, monkeypatch):
        scored = [("purchase.order", 0.56), ("sale.order", 0.30)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        outcome = resolve_dense_retrieval("bon de commande fournisseur", G, "fr_FR")
        assert outcome.candidates == ("purchase.order", "sale.order")
        assert outcome.status is SemanticRetrievalStatus.SUCCESS

    def test_ambiguous_scores_fall_through(self, monkeypatch):
        scored = [("purchase.order", 0.50), ("sale.order", 0.48)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        outcome = resolve_dense_retrieval("confirmer une commande", G, "fr_FR")
        assert outcome.candidates == ("purchase.order", "sale.order")

    def test_low_score_falls_through(self, monkeypatch):
        scored = [("res.partner", 0.15)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        outcome = resolve_dense_retrieval("inventaire galactique", G, "fr_FR")
        assert outcome.status is SemanticRetrievalStatus.SUCCESS
        assert outcome.candidates == ()

    def test_disabled_falls_through(self, monkeypatch):
        from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: ([], SemanticRetrievalStatus.DISABLED),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("purchase order", G, "en_US")
        assert result == DenseResolution(SemanticRetrievalStatus.DISABLED)

    def test_error_falls_through(self, monkeypatch):
        from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: ([], SemanticRetrievalStatus.ERROR),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("purchase order", G, "en_US")
        assert result == DenseResolution(SemanticRetrievalStatus.ERROR)

    def test_no_graph_returns_none(self):
        result = resolve_dense_retrieval("purchase order", None, "en_US")
        assert result == DenseResolution(None)

    def test_empty_results_falls_through(self, monkeypatch):
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval([]),
        )
        import networkx as nx
        G = nx.DiGraph()
        result = resolve_dense_retrieval("xyz", G, "fr_FR")
        assert result == DenseResolution(SemanticRetrievalStatus.NO_CANDIDATES)

    def test_sole_candidate_above_threshold_is_only_proposed(self, monkeypatch):
        scored = [("hr.leave", 0.45)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        G = nx.DiGraph()
        outcome = resolve_dense_retrieval("demande de conge", G, "fr_FR")
        assert outcome.status is SemanticRetrievalStatus.SUCCESS
        assert outcome.candidates == ("hr.leave",)


class TestDenseStatusVisibility:
    """The resolver exposes retrieval status when no candidate is selected."""

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
        assert outcome == DenseResolution(status)

    def test_ambiguous_fall_through_keeps_success_status(self, monkeypatch):
        scored = [("purchase.order", 0.50), ("sale.order", 0.48)]
        monkeypatch.setattr(
            "code_intelligence.agent.resolution.dense_lookup.retrieve_semantic_model_candidates_scored",
            lambda *a, **kw: _fake_scored_retrieval(scored),
        )
        import networkx as nx
        outcome = resolve_dense_retrieval("confirmer une commande", nx.DiGraph(), "fr_FR")
        assert outcome == DenseResolution(
            SemanticRetrievalStatus.SUCCESS, ("purchase.order", "sale.order"),
        )

    def test_step_not_run_without_graph(self):
        assert resolve_dense_retrieval("purchase order", None, "en_US") == DenseResolution(None)

    @pytest.mark.parametrize(
        "status", [SemanticRetrievalStatus.DISABLED, SemanticRetrievalStatus.ERROR],
    )
    def test_resolver_publishes_dense_outage_on_unresolved_concept(self, monkeypatch, status):
        from code_intelligence.agent import resolver
        import networkx as nx
        monkeypatch.setattr(
            resolver, "resolve_dense_retrieval", lambda *a, **kw: DenseResolution(status),
        )
        result = resolver.resolve_business_term("comment valider ?", nx.DiGraph(), llm=None)
        assert not result.is_resolved
        assert result.diagnostics == {"semantic_retrieval": status.value}

    def test_resolver_omits_dense_status_when_step_not_run(self, monkeypatch):
        from code_intelligence.agent import resolver
        import networkx as nx
        monkeypatch.setattr(
            resolver, "resolve_dense_retrieval", lambda *a, **kw: DenseResolution(None),
        )
        result = resolver.resolve_business_term("comment valider ?", nx.DiGraph(), llm=None)
        assert result.diagnostics == {}


class TestStaticAliasesRemoved:
    """The manual alias tables and their switches no longer exist (section 1436)."""

    def test_resolver_has_no_static_alias_switch(self):
        from code_intelligence.agent.resolver import resolve_business_term
        import inspect
        params = inspect.signature(resolve_business_term).parameters
        assert "use_static_aliases" not in params
        assert "use_static_synonyms" not in params


def test_resolver_arbitrates_when_dense_and_fuzzy_leaders_disagree(monkeypatch):
    import networkx as nx
    from code_intelligence.agent import resolver
    from code_intelligence.agent.resolution import fuzzy_lookup
    from code_intelligence.agent.resolution.arbitration import ARBITRATION_SELECTED, ArbitrationTrace

    graph = nx.DiGraph()
    for model in ("purchase.order", "sale.order"):
        graph.add_node(f"model:{model}", node_type="Model", name=model, description=model)

    monkeypatch.setattr(
        resolver,
        "resolve_dense_retrieval",
        lambda *args, **kwargs: DenseResolution(
            SemanticRetrievalStatus.SUCCESS, ("sale.order", "purchase.order"),
        ),
    )
    monkeypatch.setattr(
        fuzzy_lookup,
        "_fuzzy_match_graph",
        lambda *args, **kwargs: [("purchase.order", 95.0), ("sale.order", 45.0)],
    )
    monkeypatch.setattr(
        fuzzy_lookup,
        "_llm_arbitrate",
        lambda query, candidates, llm, contexts=None: ArbitrationTrace(
            "sale.order", ARBITRATION_SELECTED, "sale.order",
        ),
    )

    result = resolver.resolve_business_term("confirmer le bon", graph, llm=object())

    assert result.is_resolved
    assert result.resolved_models == ["sale.order"]
    assert result.source_step == "hybrid_arbitration"


def test_closed_list_keeps_the_semantic_candidate_ranked_seventh(monkeypatch):
    """A model at semantic rank 7 must reach the arbitrator (the list used to keep only 5)."""
    import networkx as nx
    from code_intelligence.agent import resolver
    from code_intelligence.agent.resolution import fuzzy_lookup
    from code_intelligence.agent.resolution.arbitration import ARBITRATION_SELECTED, ArbitrationTrace

    semantic = tuple(f"noise.model_{index}" for index in range(1, 7)) + ("hr.leave",)
    graph = nx.DiGraph()
    for model in ("lexical.leader",) + semantic:
        graph.add_node(f"model:{model}", node_type="Model", name=model, description=model)

    monkeypatch.setattr(
        resolver,
        "resolve_dense_retrieval",
        lambda *args, **kwargs: DenseResolution(SemanticRetrievalStatus.SUCCESS, semantic),
    )
    monkeypatch.setattr(
        fuzzy_lookup,
        "_fuzzy_match_graph",
        lambda *args, **kwargs: [("lexical.leader", 95.0)],
    )
    seen = {}

    def fake_arbitrate(query, candidates, llm, contexts=None):
        seen["candidates"] = list(candidates)
        return ArbitrationTrace("hr.leave", ARBITRATION_SELECTED, "hr.leave")

    monkeypatch.setattr(fuzzy_lookup, "_llm_arbitrate", fake_arbitrate)

    result = resolver.resolve_business_term("valider un conge", graph, llm=object())

    assert "hr.leave" in seen["candidates"]
    assert result.is_resolved
    assert result.resolved_models == ["hr.leave"]
    assert result.source_step == "hybrid_arbitration"


def test_resolver_abstains_when_retrievals_disagree_without_llm(monkeypatch):
    import networkx as nx
    from code_intelligence.agent import resolver
    from code_intelligence.agent.resolution import fuzzy_lookup

    graph = nx.DiGraph()
    for model in ("purchase.order", "sale.order"):
        graph.add_node(f"model:{model}", node_type="Model", name=model, description=model)

    monkeypatch.setattr(
        resolver,
        "resolve_dense_retrieval",
        lambda *args, **kwargs: DenseResolution(
            SemanticRetrievalStatus.SUCCESS, ("sale.order", "purchase.order"),
        ),
    )
    monkeypatch.setattr(
        fuzzy_lookup,
        "_fuzzy_match_graph",
        lambda *args, **kwargs: [("purchase.order", 95.0), ("sale.order", 45.0)],
    )

    result = resolver.resolve_business_term("confirmer le bon", graph, llm=None)

    assert not result.is_resolved
    assert result.source_step == "unresolved"
    assert "purchase.order" in result.diagnostics["ambiguous_candidates"]
    assert "sale.order" in result.diagnostics["ambiguous_candidates"]


def test_semantic_candidates_are_not_silently_discarded_without_llm(monkeypatch):
    import networkx as nx
    from code_intelligence.agent import resolver
    from code_intelligence.agent.resolution import fuzzy_lookup

    graph = nx.DiGraph()
    graph.add_node("model:hr.leave", node_type="Model", name="hr.leave", description="Leave requests")

    monkeypatch.setattr(
        resolver,
        "resolve_dense_retrieval",
        lambda *args, **kwargs: DenseResolution(
            SemanticRetrievalStatus.SUCCESS, ("hr.leave",),
        ),
    )
    monkeypatch.setattr(fuzzy_lookup, "_fuzzy_match_graph", lambda *args, **kwargs: [])

    result = resolver.resolve_business_term("demande d'absence", graph, llm=None)

    assert not result.is_resolved
    assert result.source_step == "unresolved"
    assert result.diagnostics["ambiguous_candidates"] == "hr.leave"
    assert result.diagnostics["arbitration_outcome"] == "no_llm"
