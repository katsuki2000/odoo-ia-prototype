"""Hermetic tests for the E1 offline harness (no network, no LLM)."""

from __future__ import annotations

import math

import networkx as nx
import numpy as np

from code_intelligence.evaluation.e1.cases import dataset_digest, load_calibration_cases
from code_intelligence.evaluation.e1.config import load_e1_config
from code_intelligence.evaluation.e1.metrics import score_resolution_case, summarize_system_scores
from code_intelligence.evaluation.e1.systems import run_r0, run_r1


def _tiny_graph():
    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        name="purchase.order",
        description="Purchase Order",
        business_labels=[{"label": "Bon de commande", "language": "fr_FR"}],
    )
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        name="sale.order",
        description="Sales Order",
        business_labels=[{"label": "Commande client", "language": "fr_FR"}],
    )
    return graph


def test_calibration_seed_loads_and_has_stable_digest():
    cases, digest, meta = load_calibration_cases()
    assert meta["status"] == "seed_incomplete"
    assert len(cases) >= 8
    assert digest == dataset_digest(cases)
    assert len(digest) == 64


def test_e1_config_has_digest_and_decision_criteria():
    config = load_e1_config()
    assert config["_digest"]
    assert "D1_hybrid_as_candidate_generator" in config["decision_criteria"]
    assert config["primary_k"] == 5


def test_r0_alias_commande_achat_hits_purchase_on_tiny_graph():
    from code_intelligence.evaluation.e1.cases import E1Case

    case = E1Case.from_dict({
        "case_id": "t_alias",
        "family": "exact_label",
        "instance": "test",
        "language": "fr_FR",
        "module": "purchase",
        "question": "commande d'achat",
        "expected_objects": ["model:purchase.order"],
        "abstention_rule": "none",
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })
    output = run_r0(case, _tiny_graph(), language="fr_FR")
    assert "purchase.order" in output.candidates


def test_r0_bon_commande_fournisseur_currently_wrong_on_alias_short_circuit():
    """Documents the production failure E1 must beat: 'commande' alias -> sale.order."""
    from code_intelligence.evaluation.e1.cases import E1Case

    case = E1Case.from_dict({
        "case_id": "t_paraphrase",
        "family": "paraphrase",
        "instance": "test",
        "language": "fr_FR",
        "module": "purchase",
        "question": "Comment confirmer un bon de commande fournisseur ?",
        "expected_objects": ["model:purchase.order"],
        "abstention_rule": "none",
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })
    output = run_r0(case, _tiny_graph(), language="fr_FR")
    score = score_resolution_case(
        case,
        candidates=output.candidates,
        declared_ambiguous=output.declared_ambiguous,
        is_resolved=output.is_resolved,
        primary_k=5,
    )
    assert score["silent_false_resolution"] is True or score["recall_at_5"] is False


def test_r1_without_aliases_does_not_use_static_table():
    from code_intelligence.evaluation.e1.cases import E1Case

    case = E1Case.from_dict({
        "case_id": "t_r1",
        "family": "exact_label",
        "instance": "test",
        "language": "fr_FR",
        "module": "purchase",
        "question": "commande d'achat",
        "expected_objects": ["model:purchase.order"],
        "abstention_rule": "none",
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })
    output = run_r1(case, _tiny_graph(), language="fr_FR")
    assert output.diagnostics["source_step"] != "static_alias"


def test_must_clarify_scoring():
    from code_intelligence.evaluation.e1.cases import E1Case

    case = E1Case.from_dict({
        "case_id": "t_amb",
        "family": "ambiguous",
        "instance": "test",
        "language": "fr_FR",
        "module": "sale",
        "question": "commande",
        "expected_objects": [],
        "abstention_rule": "must_clarify",
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })
    ok = score_resolution_case(
        case, candidates=["sale.order", "purchase.order"], declared_ambiguous=False, is_resolved=False
    )
    bad = score_resolution_case(
        case, candidates=["sale.order"], declared_ambiguous=False, is_resolved=True
    )
    assert ok["clarify_correct"] is True
    assert bad["clarify_correct"] is False


def test_summarize_by_family():
    rows = [
        {"family": "paraphrase", "recall_at_5": True, "silent_false_resolution": False, "clarify_correct": None, "correct_at_primary_k": True},
        {"family": "paraphrase", "recall_at_5": False, "silent_false_resolution": True, "clarify_correct": None, "correct_at_primary_k": False},
    ]
    summary = summarize_system_scores(rows, primary_k=5)
    assert summary["n"] == 2
    assert summary["by_family"]["paraphrase"]["n"] == 2
    assert summary["recall_at_5"] == 0.5


def test_r2_bm25_ranks_purchase_for_vendor_po_paraphrase():
    import networkx as nx
    from code_intelligence.evaluation.e1.cases import E1Case
    from code_intelligence.evaluation.e1.systems import run_r2

    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        name="purchase.order",
        description="Purchase Order",
        module="purchase",
        business_labels=[
            {"label": "Bon de commande", "language": "fr_FR"},
            {"label": "Bon de commande fournisseur", "language": "fr_FR"},
        ],
        window_actions=[{"name": "Demandes de prix", "module": "purchase"}],
    )
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        name="sale.order",
        description="Sales Order",
        module="sale",
        business_labels=[{"label": "Commande client", "language": "fr_FR"}],
    )
    graph.add_node(
        "menu:purchase.menu_purchase_rfq",
        node_type="Menu",
        xml_id="purchase.menu_purchase_rfq",
        name="Demandes de prix",
        module="purchase",
    )
    graph.add_edge(
        "menu:purchase.menu_purchase_rfq",
        "model:purchase.order",
        edge_type="OPENS_MODEL",
    )

    case = E1Case.from_dict({
        "case_id": "t_r2",
        "family": "paraphrase",
        "instance": "test",
        "language": "fr_FR",
        "module": "purchase",
        "question": "Comment confirmer un bon de commande fournisseur ?",
        "expected_objects": ["model:purchase.order"],
        "abstention_rule": "none",
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })
    output = run_r2(case, graph, language="fr_FR")
    assert output.candidates, output.diagnostics
    assert output.candidates[0] == "model:purchase.order", output
    score = score_resolution_case(
        case,
        candidates=output.candidates,
        declared_ambiguous=output.declared_ambiguous,
        is_resolved=output.is_resolved,
        primary_k=5,
    )
    assert score["recall_at_5"] is True
    assert score["silent_false_resolution"] is False


def test_query_tokenize_drops_french_stopwords():
    from code_intelligence.evaluation.e1.cards import tokenize

    tokens = tokenize("Comment confirmer un bon de commande fournisseur ?", drop_stopwords=True)
    assert "de" not in tokens
    assert "un" not in tokens
    assert "comment" not in tokens
    assert "commande" in tokens
    assert "fournisseur" in tokens


def test_labels_fall_back_when_query_language_missing():
    import networkx as nx
    from code_intelligence.evaluation.e1.cards import build_node_cards

    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        name="purchase.order",
        description="Purchase Order",
        business_labels=[{"label": "Purchase Order", "language": "en_US"}],
    )
    cards = build_node_cards(graph, language="fr_FR", node_types=["Model"])
    assert "Purchase Order" in cards[0].text


def test_build_node_cards_include_menu_path_and_hash():
    import networkx as nx
    from code_intelligence.evaluation.e1.cards import build_node_cards

    graph = nx.DiGraph()
    graph.add_node("model:purchase.order", node_type="Model", name="purchase.order", description="PO")
    graph.add_node("menu:purchase.menu_purchase_root", node_type="Menu", xml_id="purchase.menu_purchase_root", name="Achats")
    graph.add_node("menu:purchase.menu_purchase_rfq", node_type="Menu", xml_id="purchase.menu_purchase_rfq", name="Demandes de prix")
    graph.add_edge("menu:purchase.menu_purchase_rfq", "menu:purchase.menu_purchase_root", edge_type="CHILD_OF")
    graph.add_edge("menu:purchase.menu_purchase_rfq", "model:purchase.order", edge_type="OPENS_MODEL")

    cards = {card.object_ref: card for card in build_node_cards(graph, language="fr_FR")}
    assert "model:purchase.order" in cards
    assert "menus:" in cards["model:purchase.order"].text
    assert "Achats" in cards["model:purchase.order"].text
    assert len(cards["model:purchase.order"].text_hash) == 64


class _FakeTokenEmbedding:
    """Deterministic bag-of-token hashing for hermetic dense tests (no network)."""

    dim = 64

    def name(self) -> str:
        return "fake-token-hash"

    def __call__(self, input):
        vectors = []
        for text in input:
            vec = [0.0] * self.dim
            for token in str(text).casefold().replace("?", " ").split():
                vec[hash(token) % self.dim] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


def test_r3_dense_ranks_purchase_for_vendor_po_paraphrase():
    import networkx as nx
    from code_intelligence.evaluation.e1.cases import E1Case
    from code_intelligence.evaluation.e1.systems import run_r3

    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        name="purchase.order",
        description="Purchase Order",
        module="purchase",
        business_labels=[
            {"label": "Bon de commande", "language": "fr_FR"},
            {"label": "Bon de commande fournisseur", "language": "fr_FR"},
        ],
    )
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        name="sale.order",
        description="Sales Order",
        module="sale",
        business_labels=[{"label": "Commande client", "language": "fr_FR"}],
    )
    case = E1Case.from_dict({
        "case_id": "t_r3",
        "family": "paraphrase",
        "instance": "test",
        "language": "fr_FR",
        "module": "purchase",
        "question": "Comment confirmer un bon de commande fournisseur ?",
        "expected_objects": ["model:purchase.order"],
        "abstention_rule": "none",
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })
    output = run_r3(
        case, graph, language="fr_FR", embedding_function=_FakeTokenEmbedding(),
    )
    assert output.candidates, output.diagnostics
    assert output.candidates[0] == "model:purchase.order", output
    score = score_resolution_case(
        case,
        candidates=output.candidates,
        declared_ambiguous=output.declared_ambiguous,
        is_resolved=output.is_resolved,
        primary_k=5,
    )
    assert score["recall_at_5"] is True


def _cache_graph():
    graph = nx.DiGraph()
    for name, description in (
        ("purchase.order", "Purchase Order"),
        ("sale.order", "Sales Order"),
        ("hr.leave", "Time Off"),
    ):
        graph.add_node(f"model:{name}", node_type="Model", name=name, description=description)
    return graph


def _length_embedding(texts):
    return [[float(len(text)), float(sum(map(ord, text)) % 97) + 1.0, 1.0] for text in texts]


def test_dense_build_keeps_vectors_of_completed_batches_when_a_later_batch_fails(tmp_path):
    import pytest
    from code_intelligence.evaluation.e1.dense_index import DenseCardIndex

    calls = {"n": 0}

    def failing_after_first_batch(texts):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConnectionError("tunnel dropped")
        return _length_embedding(texts)

    graph = _cache_graph()
    cache_dir = str(tmp_path / "e1_dense")
    with pytest.raises(ConnectionError):
        DenseCardIndex.build(
            graph, failing_after_first_batch, node_types=("Model",), batch_size=1, cache_dir=cache_dir,
        )

    embedded: list[str] = []

    def counting(texts):
        embedded.extend(texts)
        return _length_embedding(texts)

    index = DenseCardIndex.build(
        graph, counting, node_types=("Model",), batch_size=1, cache_dir=cache_dir,
    )
    assert len(index.cards) == 3
    # One card was saved before the failure: only the two missing cards are embedded again.
    assert len(embedded) == 2
    assert len(index.vectors) == 3


def _ranking_graph():
    graph = nx.DiGraph()
    for name, description in (
        ("purchase.order", "Purchase Order"),
        ("sale.order", "Sales Order"),
        ("hr.leave", "Time Off"),
        ("account.move", "Journal Entry"),
        ("stock.picking", "Transfer"),
    ):
        graph.add_node(f"model:{name}", node_type="Model", name=name, description=description)
    for xml_id, label in (("purchase.menu_rfq", "Requests for Quotation"), ("hr.menu_leave", "Time Off")):
        graph.add_node(f"menu:{xml_id}", node_type="Menu", xml_id=xml_id, label=label)
    return graph


def _hashed_embedding(texts):
    vectors = []
    for text in texts:
        seed = sum(ord(char) * (position + 1) for position, char in enumerate(text))
        vectors.append([math.sin(seed * (axis + 1) * 0.37) for axis in range(6)])
    return vectors


def _plain_cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    return dot / (math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right)))


def test_dense_search_ranks_like_a_plain_cosine_loop(tmp_path):
    import pytest
    from code_intelligence.evaluation.e1.dense_index import DenseCardIndex

    index = DenseCardIndex.build(
        _ranking_graph(), _hashed_embedding, batch_size=3, cache_dir=str(tmp_path / "e1_dense"),
    )
    query_vector = _hashed_embedding(["purchase order"])[0]
    expected = sorted(
        (-score, card.object_ref)
        for card in index.cards
        if card.node_type == "Model"
        for score in [_plain_cosine(query_vector, _hashed_embedding([card.text])[0])]
        if score > 0.0
    )

    hits = index.search("purchase order", _hashed_embedding, top_k=3, node_types=["Model"])

    assert 0 < len(expected)
    assert [hit.object_ref for hit in hits] == [ref for _, ref in expected[:3]]
    assert [hit.score for hit in hits] == pytest.approx([-score for score, _ in expected[:3]], abs=1e-5)
    assert {hit.node_type for hit in hits} == {"Model"}


def test_dense_search_breaks_score_ties_by_object_reference(tmp_path):
    from code_intelligence.evaluation.e1.dense_index import DenseCardIndex

    def constant_embedding(texts):
        return [[1.0, 2.0, 2.0] for _ in texts]

    index = DenseCardIndex.build(
        _ranking_graph(), constant_embedding, node_types=("Model",), cache_dir=str(tmp_path / "e1_dense"),
    )

    hits = index.search("anything", constant_embedding, top_k=10)

    assert [hit.object_ref for hit in hits] == sorted(card.object_ref for card in index.cards)


def test_dense_search_ignores_zero_and_mismatched_query_vectors(tmp_path):
    from code_intelligence.evaluation.e1.dense_index import DenseCardIndex

    index = DenseCardIndex.build(
        _cache_graph(), _length_embedding, node_types=("Model",), cache_dir=str(tmp_path / "e1_dense"),
    )

    assert index.search("x", lambda texts: [[0.0, 0.0, 0.0]]) == []
    assert index.search("x", lambda texts: [[1.0, 2.0]]) == []


def test_dense_build_serves_a_complete_cache_as_a_unit_float32_matrix(tmp_path):
    from code_intelligence.evaluation.e1.dense_index import DenseCardIndex

    graph = _cache_graph()
    cache_dir = str(tmp_path / "e1_dense")
    DenseCardIndex.build(graph, _length_embedding, node_types=("Model",), cache_dir=cache_dir)

    def forbidden(texts):
        raise AssertionError("the cache already covers every card")

    index = DenseCardIndex.build(graph, forbidden, node_types=("Model",), cache_dir=cache_dir)

    assert index.vectors.dtype == np.float32
    assert index.vectors.shape == (3, 3)
    assert np.allclose(np.linalg.norm(index.vectors, axis=1), 1.0, atol=1e-6)


def test_run_offline_keeps_other_systems_when_one_fails_and_persists_each_result(tmp_path, monkeypatch):
    import json

    from code_intelligence.evaluation.e1 import run as e1_run

    real_run_system = e1_run.run_system

    def flaky_run_system(system_id, case, graph, **kwargs):
        if system_id == "R3":
            raise ConnectionError("RemoteDisconnected")
        return real_run_system(system_id, case, graph, **kwargs)

    monkeypatch.setattr(e1_run, "run_system", flaky_run_system)
    output_path = tmp_path / "report.json"
    seen: list[tuple[str, str]] = []

    report = e1_run.run_offline(
        ["R0", "R3", "R1"],
        graph=_tiny_graph(),
        output_path=output_path,
        on_system_done=lambda system_id, block: seen.append((system_id, block["status"])),
    )

    assert seen == [("R0", "scored"), ("R3", "error"), ("R1", "scored")]
    assert report["status"] == "partial"
    assert "ConnectionError" in report["systems"]["R3"]["detail"]
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "partial"
    assert persisted["systems"]["R0"]["status"] == "scored"
    assert persisted["systems"]["R1"]["status"] == "scored"


def test_run_offline_loads_graph_with_every_case_language(monkeypatch):
    from code_intelligence.evaluation.e1 import run as e1_run
    from code_intelligence.graph import loader

    received: dict = {}

    def fake_loader(**kwargs):
        received.update(kwargs)
        return _tiny_graph()

    monkeypatch.setattr(loader, "get_code_intelligence_graph", fake_loader)
    report = e1_run.run_offline([])

    assert report["status"] == "ok"
    cases, _digest, _meta = load_calibration_cases()
    assert received["translation_languages"] == sorted({case.language for case in cases})
    assert "fr_FR" in received["translation_languages"]
