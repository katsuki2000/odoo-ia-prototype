import pytest

import networkx as nx

from code_intelligence.agent.resolution.semantic_retrieval import (
    SemanticRetrieval,
    SemanticRetrievalStatus,
    configured_semantic_model_candidates,
    rank_semantic_model_candidates,
    retrieve_semantic_model_candidates,
)
from code_intelligence.agent.resolution import semantic_retrieval as semantic_module
from code_intelligence.agent.resolution.arbitration import ARBITRATION_SELECTED, ArbitrationTrace


@pytest.fixture(autouse=True)
def _fresh_query_embedding_cache():
    semantic_module._QUERY_EMBEDDING_CACHE.clear()
    yield
    semantic_module._QUERY_EMBEDDING_CACHE.clear()


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
        name="purchase.order",
        description="Purchase Order",
        business_labels=[{"label": "Demande de prix", "language": "fr_FR"}],
    )
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        name="sale.order",
        description="Sales Order",
        business_labels=[{"label": "Commande client", "language": "fr_FR"}],
    )
    return graph


def test_semantic_ranking_uses_instance_translations():
    candidates = rank_semantic_model_candidates(
        "Ou gerer une commande client ?",
        _graph_with_translated_models(),
        FakeEmbeddingFunction(),
    )

    assert candidates == ["sale.order", "purchase.order"]


def test_configured_retrieval_returns_nothing_when_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "false")

    assert configured_semantic_model_candidates(
        "commande client",
        _graph_with_translated_models(),
        "fr",
    ) == []


def test_configured_retrieval_is_enabled_when_variable_is_unset(monkeypatch):
    monkeypatch.delenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", raising=False)
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


def test_empty_candidate_list_does_not_call_the_arbiter(monkeypatch):
    from code_intelligence.agent.resolution import resolver
    from code_intelligence.agent.resolution import candidates, fuzzy_lookup

    monkeypatch.setattr(fuzzy_lookup, "_fuzzy_match_graph", lambda *a, **k: [])
    monkeypatch.setattr(
        candidates, "retrieve_semantic_model_candidates",
        lambda q, g, lang, limit=None: SemanticRetrieval([], SemanticRetrievalStatus.NO_CANDIDATES),
    )
    monkeypatch.setattr(
        fuzzy_lookup, "_llm_arbitrate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("arbiter must not be called")),
    )

    result = resolver.resolve_business_term(
        "qui peut rouvrir cela ?", _graph_with_translated_models(), llm=object(), language="fr",
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


class RecordingEmbeddingFunction(FakeEmbeddingFunction):
    def __init__(self, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def __call__(self, texts):
        self.calls.append(list(texts))
        if self.fail_on_call == len(self.calls):
            raise ConnectionError("tunnel dropped")
        return super().__call__(texts)

    def embedded_documents(self):
        return [text for call in self.calls if call != [RANKED_QUESTION] for text in call]


RANKED_QUESTION = "Ou gerer une commande client ?"


def _rank(graph, embedding_function, cache_dir):
    return rank_semantic_model_candidates(
        RANKED_QUESTION, graph, embedding_function, cache_dir=str(cache_dir),
    )


def test_persisted_index_is_reused_by_a_new_process(tmp_path):
    first = RecordingEmbeddingFunction()
    _rank(_graph_with_translated_models(), first, tmp_path)
    second = RecordingEmbeddingFunction()

    candidates = _rank(_graph_with_translated_models(), second, tmp_path)

    assert candidates == ["sale.order", "purchase.order"]
    assert len(first.embedded_documents()) == 2
    assert second.embedded_documents() == []


def test_only_changed_labels_are_embedded_again(tmp_path):
    _rank(_graph_with_translated_models(), RecordingEmbeddingFunction(), tmp_path)
    graph = _graph_with_translated_models()
    graph.nodes["model:purchase.order"]["business_labels"] = [{"label": "Achat", "language": "fr_FR"}]
    recorder = RecordingEmbeddingFunction()

    _rank(graph, recorder, tmp_path)

    assert len(recorder.embedded_documents()) == 1
    assert "Achat" in recorder.embedded_documents()[0]


def test_ranking_without_cache_dir_leaves_the_disk_untouched(tmp_path):
    rank_semantic_model_candidates(
        "commande client", _graph_with_translated_models(), RecordingEmbeddingFunction(),
    )

    assert list(tmp_path.iterdir()) == []


def test_embedding_function_receives_no_forced_model_when_unset(monkeypatch):
    from code_intelligence.agent.resolution.semantic_retrieval import build_semantic_embedding_function

    captured = {}
    monkeypatch.delenv("RESOLVER_SEMANTIC_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **kwargs: captured.update(kwargs) or FakeEmbeddingFunction(),
    )

    assert isinstance(build_semantic_embedding_function(), FakeEmbeddingFunction)
    assert captured == {"embedding_model": None}


def test_resolver_model_override_wins_over_global_embedding_model(monkeypatch):
    from code_intelligence.agent.resolution.semantic_retrieval import build_semantic_embedding_function

    captured = {}
    monkeypatch.setenv("RESOLVER_SEMANTIC_EMBEDDING_MODEL", "resolver-model")
    monkeypatch.setenv("EMBEDDING_MODEL", "global-model")
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **kwargs: captured.update(kwargs) or FakeEmbeddingFunction(),
    )

    build_semantic_embedding_function()

    assert captured["embedding_model"] == "resolver-model"


def test_query_embedding_is_computed_once_for_repeated_ranking():
    import networkx as nx

    module = semantic_module

    class CountingEmbedding:
        def __init__(self):
            self.query_calls = 0

        def name(self):
            return "counting_embedding_1325"

        def __call__(self, texts):
            if len(texts) == 1 and texts[0] == "question unique 1325":
                self.query_calls += 1
            return [[1.0, float(len(text) % 3)] for text in texts]

    graph = nx.DiGraph()
    graph.add_node("model:sale.order", node_type="Model", name="sale.order", description="Sales Order")
    embedding = CountingEmbedding()
    module.rank_semantic_model_candidates_scored("question unique 1325", graph, embedding)
    module.rank_semantic_model_candidates("question unique 1325", graph, embedding)
    assert embedding.query_calls == 1


def test_shortlist_asks_for_twenty_semantic_candidates_and_keeps_a_model_ranked_seventeenth(monkeypatch):
    from code_intelligence.agent.resolution import candidates

    semantic_models = [f"dense.model_{rank}" for rank in range(1, 21)]
    semantic_models[16] = "hr.leave"
    requested = {}

    def _retrieve(query, graph, language, limit=None):
        requested["limit"] = limit
        return SemanticRetrieval(semantic_models[:limit], SemanticRetrievalStatus.SUCCESS)

    monkeypatch.setattr(candidates, "retrieve_semantic_model_candidates", _retrieve)
    fuzzy = [(f"fuzzy.model_{index}", 90.0 - index) for index in range(8)]

    shortlist = candidates.build_arbitration_shortlist("validation des conges", None, "fr", True, fuzzy)

    assert requested["limit"] == candidates.SHORTLIST_SEMANTIC_LIMIT == 20
    assert "hr.leave" in shortlist.models
    assert shortlist.models[: candidates.SHORTLIST_FUZZY_LIMIT] == [f"fuzzy.model_{index}" for index in range(5)]
    assert len(shortlist.models) == candidates.SHORTLIST_FUZZY_LIMIT + candidates.SHORTLIST_SEMANTIC_LIMIT


def test_shortlist_without_semantic_candidates_is_the_unchanged_fuzzy_list(monkeypatch):
    from code_intelligence.agent.resolution import candidates

    monkeypatch.setattr(
        candidates, "retrieve_semantic_model_candidates",
        lambda q, g, lang, limit=None: SemanticRetrieval([], SemanticRetrievalStatus.ERROR),
    )
    fuzzy = [(f"fuzzy.model_{index}", 90.0 - index) for index in range(12)]

    shortlist = candidates.build_arbitration_shortlist("question", None, "fr", True, fuzzy)

    assert shortlist.models == [model for model, _score in fuzzy]
    assert shortlist.semantic_status == SemanticRetrievalStatus.ERROR


def _graph_with_menu():
    graph = nx.DiGraph()
    graph.add_node("model:sale.order", node_type="Model", name="sale.order", description="Sales Order")
    graph.add_node("model:res.partner", node_type="Model", name="res.partner", description="Contact")
    graph.add_node("menu:sale.menu_quotations", node_type="Menu", xml_id="sale.menu_quotations", description="Devis clients")
    graph.add_edge("menu:sale.menu_quotations", "model:sale.order", edge_type="OPENS_MODEL")
    return graph


def test_menu_card_is_a_second_document_of_the_model_it_opens():
    documents = semantic_module._model_documents(_graph_with_menu())
    assert [model for model, _text in documents].count("sale.order") == 2
    assert [model for model, _text in documents].count("res.partner") == 1
    assert any("Devis clients" in text for model, text in documents if model == "sale.order")


def test_model_card_carries_the_technical_name():
    documents = dict(semantic_module._model_documents(_graph_with_menu()))
    assert "technical: res.partner" in documents["res.partner"]


def test_ranking_keeps_the_best_document_per_model_without_duplicates():
    ranked = rank_semantic_model_candidates("Ou gerer une commande client ?", _graph_with_menu(), FakeEmbeddingFunction())
    assert ranked.count("sale.order") == 1
    assert set(ranked) == {"sale.order", "res.partner"}


def test_warm_up_persists_the_index_so_the_first_question_embeds_no_document(monkeypatch, tmp_path):
    from code_intelligence.agent.resolution.semantic_retrieval import warm_semantic_index

    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")
    monkeypatch.setattr(semantic_module.settings, "SEMANTIC_INDEX_CACHE_DIR", str(tmp_path))
    warming = RecordingEmbeddingFunction()
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function", lambda **_kwargs: warming,
    )

    statuses = warm_semantic_index(_graph_with_translated_models(), ["fr"])

    assert statuses == [SemanticRetrievalStatus.SUCCESS]
    first_question = RecordingEmbeddingFunction()
    _rank(_graph_with_translated_models(), first_question, tmp_path)
    assert first_question.embedded_documents() == []


def test_warm_up_failure_is_a_status_not_an_exception(monkeypatch, tmp_path):
    from code_intelligence.agent.resolution.semantic_retrieval import warm_semantic_index

    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "true")
    monkeypatch.setattr(semantic_module.settings, "SEMANTIC_INDEX_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "document_rag.vectorstore.embedding_functions.resolve_embedding_function",
        lambda **_kwargs: RecordingEmbeddingFunction(fail_on_call=1),
    )

    assert warm_semantic_index(_graph_with_translated_models(), []) == [SemanticRetrievalStatus.ERROR]
