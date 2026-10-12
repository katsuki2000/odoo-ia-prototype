"""Hermetic tests for E1 R4 (reciprocal rank fusion of BM25 and dense rankings)."""

from __future__ import annotations

import networkx as nx
import pytest

from code_intelligence.evaluation.e1 import hybrid, systems
from code_intelligence.evaluation.e1.cases import E1Case
from code_intelligence.evaluation.e1.fusion import reciprocal_rank_fusion
from code_intelligence.evaluation.e1.systems import SystemOutput, run_system


class _FakeTokenEmbedding:
    dim = 64

    def name(self) -> str:
        return "fake-token-hash-r4"

    def __call__(self, input):
        vectors = []
        for text in input:
            vec = [0.0] * self.dim
            for token in str(text).casefold().replace("?", " ").split():
                vec[hash(token) % self.dim] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


def _case(expected="model:purchase.order"):
    return E1Case.from_dict({
        "case_id": "t_r4",
        "family": "paraphrase",
        "instance": "test",
        "language": "fr_FR",
        "module": "purchase",
        "question": "Comment confirmer un bon de commande fournisseur ?",
        "expected_objects": [expected],
        "abstention_rule": "none",
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })


def _output(system_id, candidates, *, resolved=False, ambiguous=False):
    return SystemOutput(
        system_id=system_id,
        candidates=tuple(candidates),
        declared_ambiguous=ambiguous,
        is_resolved=resolved,
        diagnostics={},
    )


def test_rrf_scores_and_order():
    fused = reciprocal_rank_fusion(
        {"a": ["x", "y", "z"], "b": ["y", "x"]}, constant=60,
    )
    refs = [ref for ref, _ in fused]
    scores = dict(fused)
    assert refs[:2] == ["x", "y"]
    assert scores["x"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["y"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["z"] == pytest.approx(1 / 63)


def test_rrf_is_deterministic_on_ties_and_honours_weights():
    tied = reciprocal_rank_fusion({"a": ["m"], "b": ["n"]})
    assert [ref for ref, _ in tied] == ["m", "n"]
    weighted = reciprocal_rank_fusion({"a": ["m"], "b": ["n"]}, weights={"a": 1.0, "b": 2.0})
    assert [ref for ref, _ in weighted] == ["n", "m"]


def test_rrf_ignores_duplicates_and_rejects_negative_constant():
    fused = dict(reciprocal_rank_fusion({"a": ["x", "x", "y"]}))
    assert fused["x"] == pytest.approx(1 / 61)
    assert fused["y"] == pytest.approx(1 / 62)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"a": ["x"]}, constant=-1)


def test_r4_resolves_when_both_retrievers_agree_on_top1(monkeypatch):
    monkeypatch.setattr(systems, "run_r2", lambda *a, **k: _output("R2", ["model:purchase.order", "model:sale.order"]))
    monkeypatch.setattr(systems, "run_r3", lambda *a, **k: _output("R3", ["model:purchase.order"], ambiguous=True))
    result = hybrid.run_r4(_case(), nx.DiGraph())
    assert result.system_id == "R4"
    assert result.candidates == ("model:purchase.order", "model:sale.order")
    assert result.is_resolved and not result.declared_ambiguous


def test_r4_declares_ambiguity_when_top1_disagree(monkeypatch):
    monkeypatch.setattr(systems, "run_r2", lambda *a, **k: _output("R2", ["model:sale.order", "model:purchase.order"]))
    monkeypatch.setattr(systems, "run_r3", lambda *a, **k: _output("R3", ["model:purchase.order", "model:sale.order"]))
    result = hybrid.run_r4(_case(), nx.DiGraph())
    assert set(result.candidates) == {"model:sale.order", "model:purchase.order"}
    assert result.declared_ambiguous and not result.is_resolved


def test_r4_single_retriever_inherits_its_flags(monkeypatch):
    monkeypatch.setattr(systems, "run_r2", lambda *a, **k: _output("R2", []))
    monkeypatch.setattr(systems, "run_r3", lambda *a, **k: _output("R3", ["model:purchase.order"], resolved=True))
    result = hybrid.run_r4(_case(), nx.DiGraph())
    assert result.candidates == ("model:purchase.order",)
    assert result.is_resolved and not result.declared_ambiguous


def test_r4_empty_when_neither_retriever_hits(monkeypatch):
    monkeypatch.setattr(systems, "run_r2", lambda *a, **k: _output("R2", []))
    monkeypatch.setattr(systems, "run_r3", lambda *a, **k: _output("R3", []))
    result = hybrid.run_r4(_case(), nx.DiGraph())
    assert result.candidates == ()
    assert not result.is_resolved and not result.declared_ambiguous


def test_r4_end_to_end_on_tiny_graph_with_fake_embedding():
    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order", node_type="Model", name="purchase.order",
        description="Purchase Order", module="purchase",
        business_labels=[{"label": "Bon de commande fournisseur", "language": "fr_FR"}],
    )
    graph.add_node(
        "model:sale.order", node_type="Model", name="sale.order",
        description="Sales Order", module="sale",
        business_labels=[{"label": "Commande client", "language": "fr_FR"}],
    )
    result = run_system(
        "R4", _case(), graph, language="fr_FR", embedding_function=_FakeTokenEmbedding(),
    )
    assert result.candidates[0] == "model:purchase.order", result
    assert result.diagnostics["source_step"] == "rrf"
