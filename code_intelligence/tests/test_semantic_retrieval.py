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
