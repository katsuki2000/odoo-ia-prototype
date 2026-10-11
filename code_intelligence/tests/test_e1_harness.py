"""Hermetic tests for the E1 offline harness (no network, no LLM)."""

from __future__ import annotations

import networkx as nx

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
