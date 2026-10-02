import networkx as nx

from code_intelligence.agent.semantic_retrieval import (
    SemanticRetrieval,
    SemanticRetrievalStatus,
    configured_semantic_model_candidates,
    rank_semantic_model_candidates,
    retrieve_semantic_model_candidates,
)


class FakeEmbeddingFunction:
    def name(self):
        return "fake-semantic"

    def __call__(self, texts):
        vectors = []
        for text in texts:
            normalized = text.casefold()
            if "commande client" in normalized or "ou gerer" in normalized:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


def _graph_with_translated_models():
    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        description="Purchase Order",
        business_labels=[{"label": "Demande de prix", "language": "fr_FR"}],
    )
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        description="Sales Order",
        business_labels=[{"label": "Commande client", "language": "fr_FR"}],
    )
    return graph


def test_semantic_ranking_uses_instance_translations():
    candidates = rank_semantic_model_candidates(
        "Ou gerer une commande client ?",
        _graph_with_translated_models(),
        FakeEmbeddingFunction(),
        language="fr",
    )

    assert candidates == ["sale.order", "purchase.order"]


def test_configured_retrieval_returns_nothing_when_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "false")

    assert configured_semantic_model_candidates(
        "commande client",
        _graph_with_translated_models(),
        "fr",
    ) == []


def test_cosine_similarity_accepts_numpy_vectors():
    import numpy as np

    from code_intelligence.agent.semantic_retrieval import _cosine_similarity

    assert _cosine_similarity(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == 1.0
    assert _cosine_similarity(np.array([]), np.array([])) == 0.0


def test_configured_retrieval_falls_back_to_default_embeddings_for_local_light(monkeypatch):
    import sys
    import types

    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("RESOLVER_SEMANTIC_EMBEDDING_BACKEND", "local_light")
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **_kwargs: None,
    )
    fake_module = types.ModuleType("chromadb.utils.embedding_functions")
    fake_module.DefaultEmbeddingFunction = FakeEmbeddingFunction
    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", fake_module)

    candidates = configured_semantic_model_candidates(
        "Ou gerer une commande client ?",
        _graph_with_translated_models(),
        "fr",
    )

    assert candidates == ["sale.order", "purchase.order"]


def test_configured_retrieval_is_enabled_when_variable_is_unset(monkeypatch):
    monkeypatch.delenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", raising=False)
    monkeypatch.setenv("RESOLVER_SEMANTIC_EMBEDDING_BACKEND", "local_light")
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **_kwargs: FakeEmbeddingFunction(),
    )

    assert configured_semantic_model_candidates(
        "Ou gerer une commande client ?",
        _graph_with_translated_models(),
        "fr",
    ) == ["sale.order", "purchase.order"]


def test_configured_retrieval_fails_open_when_provider_raises(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")

    def _boom(**_kwargs):
        raise RuntimeError("embedding server unreachable")

    monkeypatch.setattr("document_rag.vectorstore.embedding_functions.resolve_embedding_function", _boom)

    assert configured_semantic_model_candidates("commande", _graph_with_translated_models(), "fr") == []


def test_semantic_candidates_reach_arbitration_when_widened_fuzzy_is_empty(monkeypatch):
    from code_intelligence.agent import resolver
    from code_intelligence.agent.resolution import candidates, fuzzy_lookup

    graph = _graph_with_translated_models()
    seen = {}
    monkeypatch.setattr(fuzzy_lookup, "_fuzzy_match_graph", lambda *a, **k: [])
    monkeypatch.setattr(
        candidates, "retrieve_semantic_model_candidates",
        lambda q, g, lang: SemanticRetrieval(["sale.order"], SemanticRetrievalStatus.SUCCESS),
    )

    def _arbiter(query, candidates, llm, contexts=None):
        seen["candidates"] = list(candidates)
        return candidates[0]

    monkeypatch.setattr(fuzzy_lookup, "_llm_arbitrate", _arbiter)

    result = resolver.resolve_business_term(
        "qui peut rouvrir cela ?", graph, llm=object(), language="fr", use_static_aliases=False,
    )

    assert seen["candidates"] == ["sale.order"]
    assert result.resolved_models == ["sale.order"]
    assert result.source_step == "llm_arbitration_widened"


def test_empty_candidate_list_does_not_call_the_arbiter(monkeypatch):
    from code_intelligence.agent import resolver
    from code_intelligence.agent.resolution import candidates, fuzzy_lookup

    monkeypatch.setattr(fuzzy_lookup, "_fuzzy_match_graph", lambda *a, **k: [])
    monkeypatch.setattr(
        candidates, "retrieve_semantic_model_candidates",
        lambda q, g, lang: SemanticRetrieval([], SemanticRetrievalStatus.NO_CANDIDATES),
    )
    monkeypatch.setattr(
        fuzzy_lookup, "_llm_arbitrate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("arbiter must not be called")),
    )

    result = resolver.resolve_business_term(
        "qui peut rouvrir cela ?", _graph_with_translated_models(), llm=object(), language="fr",
        use_static_aliases=False,
    )

    assert not result.is_resolved


def test_retrieval_status_is_disabled_when_switched_off(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "false")

    result = retrieve_semantic_model_candidates("commande", _graph_with_translated_models(), "fr")

    assert result.models == []
    assert result.status is SemanticRetrievalStatus.DISABLED


def test_retrieval_status_is_error_when_provider_raises(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")

    def _boom(**_kwargs):
        raise RuntimeError("embedding server unreachable")

    monkeypatch.setattr("document_rag.vectorstore.embedding_functions.resolve_embedding_function", _boom)

    result = retrieve_semantic_model_candidates("commande", _graph_with_translated_models(), "fr")

    assert result.models == []
    assert result.status is SemanticRetrievalStatus.ERROR


def test_retrieval_status_is_error_when_no_provider_is_configured(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("RESOLVER_SEMANTIC_EMBEDDING_BACKEND", "local_server")
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **_kwargs: None,
    )

    result = retrieve_semantic_model_candidates("commande", _graph_with_translated_models(), "fr")

    assert result.status is SemanticRetrievalStatus.ERROR


def test_retrieval_status_is_no_candidates_when_graph_has_no_labels(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **_kwargs: FakeEmbeddingFunction(),
    )

    result = retrieve_semantic_model_candidates("commande", nx.DiGraph(), "fr")

    assert result.models == []
    assert result.status is SemanticRetrievalStatus.NO_CANDIDATES


def test_retrieval_status_is_success_with_candidates(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **_kwargs: FakeEmbeddingFunction(),
    )

    result = retrieve_semantic_model_candidates(
        "Ou gerer une commande client ?", _graph_with_translated_models(), "fr",
    )

    assert result.models == ["sale.order", "purchase.order"]
    assert result.status is SemanticRetrievalStatus.SUCCESS


def test_resolver_publishes_semantic_status_when_arbitration_selects_nothing(monkeypatch):
    from code_intelligence.agent import resolver
    from code_intelligence.agent.resolution import candidates, fuzzy_lookup

    monkeypatch.setattr(fuzzy_lookup, "_fuzzy_match_graph", lambda *a, **k: [])
    monkeypatch.setattr(
        candidates, "retrieve_semantic_model_candidates",
        lambda q, g, lang: SemanticRetrieval([], SemanticRetrievalStatus.ERROR),
    )

    result = resolver.resolve_business_term(
        "qui peut rouvrir cela ?", _graph_with_translated_models(), llm=object(), language="fr",
        use_static_aliases=False,
    )

    assert not result.is_resolved
    assert result.diagnostics == {"semantic_retrieval": "error"}
