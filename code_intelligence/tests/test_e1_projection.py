"""Hermetic tests for E1 model projection, rescoring and ambiguous-candidate reuse."""

from __future__ import annotations

import networkx as nx
import pytest

from code_intelligence.agent.matching import ResolvedConcept
from code_intelligence.agent.resolution import fuzzy_lookup
from code_intelligence.agent.resolution.arbitration import (
    ARBITRATION_NONE,
    ARBITRATION_SELECTED,
    ArbitrationTrace,
)
from code_intelligence.agent.resolution.candidates import ArbitrationShortlist
from code_intelligence.agent.semantic_retrieval import SemanticRetrievalStatus
from code_intelligence.evaluation.e1 import run as e1_run
from code_intelligence.evaluation.e1.cases import E1Case, dataset_digest
from code_intelligence.evaluation.e1.metrics import score_resolution_case, summarize_system_scores
from code_intelligence.evaluation.e1.projection import ModelProjector, project_candidates
from code_intelligence.evaluation.e1.rescore import rescore_report
from code_intelligence.evaluation.e1.systems import SystemOutput, _from_resolved


def _case(case_id="c1", *, expected=("model:purchase.order",), rule="none", family="paraphrase"):
    return E1Case.from_dict({
        "case_id": case_id,
        "family": family,
        "instance": "test",
        "language": "fr_FR",
        "module": "purchase",
        "question": "Comment confirmer un bon de commande fournisseur ?",
        "expected_objects": list(expected),
        "abstention_rule": rule,
        "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })


def _structure_graph():
    graph = nx.DiGraph()
    for name in ("purchase.order", "sale.order"):
        graph.add_node(f"model:{name}", node_type="Model", name=name)
    graph.add_node("method:purchase.order.button_confirm", node_type="Method", name="button_confirm", model="purchase.order")
    graph.add_node("field:purchase.order.state", node_type="Field", name="state", model="purchase.order")
    graph.add_node("button:purchase.order.button_confirm", node_type="Button", name="button_confirm", model="purchase.order")
    graph.add_node("menu:purchase.menu_rfq", node_type="Menu", xml_id="purchase.menu_rfq")
    graph.add_edge("menu:purchase.menu_rfq", "model:purchase.order", edge_type="OPENS_MODEL")
    graph.add_node("menu:purchase.menu_root", node_type="Menu", xml_id="purchase.menu_root")
    graph.add_node("rule:purchase.po_rule", node_type="Rule", xml_id="purchase.po_rule")
    graph.add_edge("model:purchase.order", "rule:purchase.po_rule", edge_type="RESTRICTED_BY")
    graph.add_node("group:purchase.group_user", node_type="Group", xml_id="purchase.group_user")
    return graph


def test_projector_maps_every_card_type_to_its_parent_models():
    projector = ModelProjector(_structure_graph())

    assert projector("model:sale.order") == ("model:sale.order",)
    assert projector("method:purchase.order.button_confirm") == ("model:purchase.order",)
    assert projector("field:purchase.order.state") == ("model:purchase.order",)
    assert projector("button:purchase.order.button_confirm") == ("model:purchase.order",)
    assert projector("menu:purchase.menu_rfq") == ("model:purchase.order",)
    assert projector("rule:purchase.po_rule") == ("model:purchase.order",)


def test_projector_gives_no_model_to_groups_menus_without_action_and_unknown_references():
    projector = ModelProjector(_structure_graph())

    assert projector("group:purchase.group_user") == ()
    assert projector("menu:purchase.menu_root") == ()
    assert projector("field:unknown.model.name") == ()


def test_projection_keeps_rank_order_and_each_model_once():
    projector = ModelProjector(_structure_graph())

    projected = project_candidates(
        [
            "group:purchase.group_user",
            "field:purchase.order.state",
            "model:sale.order",
            "method:purchase.order.button_confirm",
        ],
        projector,
    )

    assert projected == ["model:purchase.order", "model:sale.order"]


def test_child_cards_of_the_expected_model_count_once_projected_and_not_raw():
    candidates = ["field:res.company.po_double_validation", "method:purchase.order.button_confirm"]
    projector = ModelProjector(nx.compose(_structure_graph(), _company_graph()))

    score = score_resolution_case(_case(), candidates=candidates, projector=projector)

    assert score["recall_at_5"] is True
    assert score["recall_at_5_raw"] is False
    assert score["projected_candidates"] == ["model:res.company", "model:purchase.order"]
    assert score["candidates"] == candidates
    assert score["correct_at_primary_k"] is True


def _company_graph():
    graph = nx.DiGraph()
    graph.add_node("model:res.company", node_type="Model", name="res.company")
    graph.add_node("field:res.company.po_double_validation", node_type="Field", name="po_double_validation", model="res.company")
    return graph


def test_without_projector_scores_are_the_raw_scores():
    score = score_resolution_case(_case(), candidates=["method:purchase.order.button_confirm"])

    assert score["recall_at_5"] is False
    assert score["recall_at_5"] == score["recall_at_5_raw"]
    assert score["projected_candidates"] is None


def test_silent_false_resolution_is_judged_on_the_projected_top_choice():
    projector = ModelProjector(_structure_graph())
    outcome = {"candidates": ["method:purchase.order.button_confirm"], "is_resolved": True, "projector": projector}

    score = score_resolution_case(_case(), **outcome)

    assert score["silent_false_resolution"] is False
    assert score["silent_false_resolution_raw"] is True


def test_cases_that_do_not_target_a_model_are_not_projected():
    projector = ModelProjector(_structure_graph())
    case = _case(expected=("menu:purchase.menu_rfq",), family="non_model")

    score = score_resolution_case(case, candidates=["field:purchase.order.state"], projector=projector)

    assert score["projected_candidates"] is None
    assert score["recall_at_5"] is False


def test_clarification_cases_are_not_projected():
    projector = ModelProjector(_structure_graph())
    case = _case(expected=(), rule="must_clarify", family="ambiguous")

    score = score_resolution_case(
        case, candidates=["model:sale.order", "model:purchase.order"], projector=projector,
    )

    assert score["projected_candidates"] is None
    assert score["clarify_correct"] is True


def test_summary_reports_raw_and_projected_rates():
    projector = ModelProjector(_structure_graph())
    scores = [
        score_resolution_case(_case("a"), candidates=["method:purchase.order.button_confirm"], projector=projector),
        score_resolution_case(_case("b"), candidates=["model:sale.order"], projector=projector),
    ]

    summary = summarize_system_scores(scores, primary_k=5)

    assert summary["recall_at_5"] == 0.5
    assert summary["recall_at_5_raw"] == 0.0
    assert summary["by_family"]["paraphrase"]["recall_at_5_raw"] == 0.0


def _saved_report(cases):
    stored = score_resolution_case(
        cases[0], candidates=["method:purchase.order.button_confirm"], declared_ambiguous=False, is_resolved=True,
    )
    return {
        "status": "ok",
        "cases_digest": dataset_digest(cases),
        "systems": {
            "R3": {"status": "scored", "summary": {}, "scores": [stored]},
            "R5": {"status": "not_implemented", "detail": "later"},
        },
    }


def test_rescore_projects_stored_candidates_without_recomputing_them():
    cases = (_case(),)
    report = _saved_report(cases)

    rescored = rescore_report(
        report, cases, ModelProjector(_structure_graph()), cases_digest=dataset_digest(cases),
    )

    row = rescored["systems"]["R3"]["scores"][0]
    assert row["recall_at_5"] is True
    assert row["recall_at_5_raw"] is False
    assert rescored["systems"]["R3"]["summary"]["recall_at_5"] == 1.0
    assert rescored["systems"]["R5"] == report["systems"]["R5"]
    assert rescored["rescored_with"] == "parent_model_projection"
    assert report["systems"]["R3"]["scores"][0]["recall_at_5"] is False


def test_rescore_refuses_a_report_computed_on_another_calibration_set():
    cases = (_case(),)

    with pytest.raises(ValueError, match="different calibration set"):
        rescore_report(
            {**_saved_report(cases), "cases_digest": "0" * 64},
            cases,
            ModelProjector(_structure_graph()),
            cases_digest=dataset_digest(cases),
        )


def test_run_offline_scores_with_model_projection(monkeypatch):
    def child_cards_only(system_id, case, graph, **kwargs):
        return SystemOutput(
            system_id=system_id,
            candidates=("method:purchase.order.button_confirm",),
            declared_ambiguous=False,
            is_resolved=True,
            diagnostics={},
        )

    monkeypatch.setattr(e1_run, "run_system", child_cards_only)

    report = e1_run.run_offline(["R3"], graph=_structure_graph())

    rows = [row for row in report["systems"]["R3"]["scores"] if row["expected_objects"] == ["model:purchase.order"]]
    assert rows
    assert all(row["recall_at_5"] is True and row["recall_at_5_raw"] is False for row in rows)


def test_system_output_reuses_the_ambiguous_candidates_an_unresolved_concept_published():
    concept = ResolvedConcept(
        user_term="q",
        is_resolved=False,
        source_step="unresolved",
        reason="Ambiguous fuzzy candidates (sale.order (90), purchase.order (90)) and LLM arbitration did not select one.",
        diagnostics={fuzzy_lookup.AMBIGUOUS_CANDIDATES_KEY: "sale.order,purchase.order"},
    )

    output = _from_resolved("R1", concept)

    assert output.candidates == ("sale.order", "purchase.order")
    assert output.declared_ambiguous is True
    assert output.is_resolved is False


def _patch_ambiguous_fuzzy_step(monkeypatch, *, arbitration_choice, semantic_status=None):
    ties = [("sale.order", 90.0), ("purchase.order", 90.0), ("account.move", 88.0)]
    monkeypatch.setattr(fuzzy_lookup, "_fuzzy_match_graph", lambda *args, **kwargs: ties)
    monkeypatch.setattr(fuzzy_lookup, "_deterministic_tiebreak", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        fuzzy_lookup,
        "build_arbitration_shortlist",
        lambda *args, **kwargs: ArbitrationShortlist([model for model, _ in ties], semantic_status),
    )
    monkeypatch.setattr(fuzzy_lookup, "_candidate_contexts", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        fuzzy_lookup,
        "_llm_arbitrate",
        lambda *args, **kwargs: ArbitrationTrace(
            arbitration_choice, ARBITRATION_SELECTED if arbitration_choice else ARBITRATION_NONE, arbitration_choice,
        ),
    )
