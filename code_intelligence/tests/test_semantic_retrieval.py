import networkx as nx

from code_intelligence.agent.semantic_retrieval import (
    configured_semantic_model_candidates,
    rank_semantic_model_candidates,
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


def test_configured_retrieval_is_disabled_by_default(monkeypatch):
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

    graph = _graph_with_translated_models()
    seen = {}
    monkeypatch.setattr(resolver, "_fuzzy_match_graph", lambda *a, **k: [])
    monkeypatch.setattr(resolver, "configured_semantic_model_candidates", lambda q, g, lang: ["sale.order"])

    def _arbiter(query, candidates, llm, contexts=None):
        seen["candidates"] = list(candidates)
        return candidates[0]

    monkeypatch.setattr(resolver, "_llm_arbitrate", _arbiter)

    result = resolver.resolve_business_term(
        "qui peut rouvrir cela ?", graph, llm=object(), language="fr", use_static_aliases=False,
    )

    assert seen["candidates"] == ["sale.order"]
    assert result.resolved_models == ["sale.order"]
    assert result.source_step == "llm_arbitration_widened"


def test_empty_candidate_list_does_not_call_the_arbiter(monkeypatch):
    from code_intelligence.agent import resolver

    monkeypatch.setattr(resolver, "_fuzzy_match_graph", lambda *a, **k: [])
    monkeypatch.setattr(resolver, "configured_semantic_model_candidates", lambda q, g, lang: [])
    monkeypatch.setattr(
        resolver, "_llm_arbitrate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("arbiter must not be called")),
    )

    result = resolver.resolve_business_term(
        "qui peut rouvrir cela ?", _graph_with_translated_models(), llm=object(), language="fr",
        use_static_aliases=False,
    )

    assert not result.is_resolved
