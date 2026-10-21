"""Hermetic tests for the E1 arbitration contract and system R6 (fake LLM, no network)."""

from __future__ import annotations

import networkx as nx
import pytest

from code_intelligence.evaluation.e1 import arbitrated, hybrid
from code_intelligence.evaluation.e1.arbitration import (
    ArbitrationStatus,
    arbitrate,
    parse_output,
)
from code_intelligence.evaluation.e1.cases import E1Case
from code_intelligence.evaluation.e1.systems import SystemOutput, run_system

CANDIDATES = ["model:purchase.order", "model:sale.order"]
ANNOTATED = [(ref, f"card of {ref}") for ref in CANDIDATES]


def _fixed(answer):
    return lambda _system, _user: answer


def _failing(_system, _user):
    raise ConnectionError("tunnel down")


def test_exact_identifier_is_chosen():
    result = arbitrate("q", ANNOTATED, _fixed("model:sale.order"))
    assert result.status is ArbitrationStatus.CHOSEN
    assert result.choice == "model:sale.order"


def test_none_is_not_a_resolution():
    result = arbitrate("q", ANNOTATED, _fixed("NONE"))
    assert (result.status, result.choice) == (ArbitrationStatus.NONE, None)


def test_ambiguous_is_not_a_resolution():
    result = arbitrate("q", ANNOTATED, _fixed("AMBIGU"))
    assert (result.status, result.choice) == (ArbitrationStatus.AMBIGUOUS, None)


@pytest.mark.parametrize(
    "answer",
    ["model:account.move", "model:purchase.order.", "model:purchase.order, model:sale.order",
     "Le modèle purchase.order", "", "none", "ambigu"],
)
def test_any_other_output_is_invalid(answer):
    result = arbitrate("q", ANNOTATED, _fixed(answer))
    assert (result.status, result.choice) == (ArbitrationStatus.INVALID, None)


def test_bare_identifier_matching_one_candidate_is_chosen_with_its_full_identifier():
    result = arbitrate("q", ANNOTATED, _fixed("purchase.order"))
    assert (result.status, result.choice) == (ArbitrationStatus.CHOSEN, "model:purchase.order")
    assert result.raw == "purchase.order"


def test_bare_identifier_shared_by_two_candidate_kinds_stays_invalid():
    candidates = ["model:sale.order", "menu:sale.order"]
    assert parse_output("sale.order", candidates) == (ArbitrationStatus.INVALID, None)


@pytest.mark.parametrize(
    "answer",
    ["account.move", "purchase.order.", '"purchase.order"', "`purchase.order`", "purchase.order, sale.order", "Purchase.Order"],
)
def test_bare_identifier_outside_the_list_or_with_extra_characters_stays_invalid(answer):
    assert parse_output(answer, CANDIDATES) == (ArbitrationStatus.INVALID, None)


def test_bare_identifier_after_a_reasoning_block_is_chosen():
    raw = "<think>achat ou vente ?</think>\npurchase.order"
    assert parse_output(raw, CANDIDATES) == (ArbitrationStatus.CHOSEN, "model:purchase.order")


def test_llm_failure_is_a_distinct_status_with_no_choice():
    result = arbitrate("q", ANNOTATED, _failing)
    assert result.status is ArbitrationStatus.LLM_ERROR
    assert result.choice is None
    assert "ConnectionError" in result.raw


def test_reasoning_block_is_removed_before_reading():
    raw = "<think>purchase.order ou sale.order ?\nplutôt achat</think>\nmodel:purchase.order"
    assert parse_output(raw, CANDIDATES) == (ArbitrationStatus.CHOSEN, "model:purchase.order")


def test_a_choice_inside_the_reasoning_block_does_not_count():
    assert parse_output("<think>model:purchase.order</think>", CANDIDATES)[0] is ArbitrationStatus.INVALID


def test_the_five_statuses_are_distinct():
    outcomes = {
        arbitrate("q", ANNOTATED, llm).status
        for llm in (_fixed(CANDIDATES[0]), _fixed("NONE"), _fixed("AMBIGU"), _fixed("x"), _failing)
    }
    assert len(outcomes) == 5


def test_prompt_lists_the_candidates_and_the_instance_priority_rule():
    seen = {}

    def spy(system_prompt, user_prompt):
        seen["system"], seen["user"] = system_prompt, user_prompt
        return "NONE"

    arbitrate("bon de commande", ANNOTATED, spy)
    assert "L'instance prime" in seen["system"]
    assert "bon de commande" in seen["user"]
    assert all(ref in seen["user"] and f"card of {ref}" in seen["user"] for ref in CANDIDATES)
    assert "NONE" in seen["user"] and "AMBIGU" in seen["user"]


# ---------------------------------------------------------------- R6


def _graph():
    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order", node_type="Model", name="purchase.order", module="purchase",
        business_labels=[{"label": "Bon de commande fournisseur", "language": "fr"}],
    )
    graph.add_node("model:sale.order", node_type="Model", name="sale.order", module="sale")
    graph.add_node(
        "method:purchase.order.button_confirm", node_type="Method", name="button_confirm",
        model="purchase.order",
    )
    return graph


def _case(expected="model:purchase.order", rule="none"):
    return E1Case.from_dict({
        "case_id": "t_r6", "family": "paraphrase", "instance": "t", "language": "fr_FR", "module": "purchase",
        "question": "confirmer un bon de commande", "expected_objects": [expected],
        "abstention_rule": rule, "ground_truth": {"author": "t", "method": "human_review", "reference": "t"},
    })


def _config(fixed=True):
    return {"decision_criteria": {"R6": {"thresholds_fixed": fixed}}, "arbitration": {"top_k": 5}}


@pytest.fixture
def r4(monkeypatch):
    def install(candidates):
        monkeypatch.setattr(
            hybrid, "run_r4",
            lambda *a, **k: SystemOutput("R4", tuple(candidates), False, False, {"source_step": "rrf"}),
        )
    return install


def test_r6_shortlist_is_projected_on_models_and_the_choice_comes_first(r4):
    r4(["method:purchase.order.button_confirm", "model:sale.order", "model:purchase.order"])
    seen = {}

    def llm(_system, user):
        seen["user"] = user
        return "model:sale.order"

    out = arbitrated.run_r6(_case(), _graph(), config=_config(), llm=llm)

    assert out.is_resolved and not out.declared_ambiguous
    assert out.candidates == ("model:sale.order", "model:purchase.order")
    assert out.diagnostics["shortlist"] == ["model:purchase.order", "model:sale.order"]
    assert out.diagnostics["arbitration_status"] == "CHOSEN"
    assert "Bon de commande fournisseur" in seen["user"]


def test_r6_ambiguous_keeps_the_list_for_clarification(r4):
    r4(["model:purchase.order", "model:sale.order"])
    out = arbitrated.run_r6(_case(), _graph(), config=_config(), llm=_fixed("AMBIGU"))
    assert not out.is_resolved and out.declared_ambiguous
    assert out.candidates == ("model:purchase.order", "model:sale.order")


@pytest.mark.parametrize("llm,status", [(_fixed("NONE"), "NONE"), (_fixed("zzz"), "INVALID"), (_failing, "LLM_ERROR")])
def test_r6_non_resolving_statuses_never_pick_a_default(r4, llm, status):
    r4(["model:purchase.order", "model:sale.order"])
    out = arbitrated.run_r6(_case(), _graph(), config=_config(), llm=llm)
    assert not out.is_resolved and not out.declared_ambiguous
    assert out.diagnostics["arbitration_status"] == status


def test_r6_without_candidates_does_not_call_the_llm(r4):
    r4([])
    out = arbitrated.run_r6(_case(), _graph(), config=_config(), llm=_failing)
    assert out.candidates == () and not out.is_resolved
    assert out.diagnostics["arbitration_status"] == "NO_CANDIDATES"


def test_r6_refuses_to_compute_before_the_thresholds_are_fixed(r4):
    r4(["model:purchase.order"])
    with pytest.raises(RuntimeError, match="thresholds"):
        arbitrated.run_r6(_case(), _graph(), config=_config(fixed=False), llm=_fixed("NONE"))


def test_r6_requires_an_llm(r4):
    r4(["model:purchase.order"])
    with pytest.raises(RuntimeError, match="LLM"):
        arbitrated.run_r6(_case(), _graph(), config=_config(), llm=None)


def test_run_system_routes_r6_with_the_injected_llm(r4):
    r4(["model:purchase.order", "model:sale.order"])
    out = run_system("R6", _case(), _graph(), config=_config(), llm=_fixed("model:purchase.order"))
    assert out.system_id == "R6" and out.candidates[0] == "model:purchase.order"


def test_shipped_configuration_fixes_the_r6_thresholds_and_drops_the_held_out_clause():
    from code_intelligence.evaluation.e1.config import load_e1_config

    config = load_e1_config()
    criteria = config["decision_criteria"]
    r6 = criteria["R6"]
    assert "R6" in config["systems"]
    assert r6["thresholds_fixed"] is True and r6["fixed_in_section"] == 1290
    assert r6["max_silent_false_vs_R4"] == 0.0
    assert r6["min_correct_decision_non_ambiguous"] == 0.8
    assert r6["min_strict_clarification_ambiguous_and_absent"] == 1.0
    assert set(r6["denominators"]) == {"silent_false", "correct_decision", "strict_clarification"}
    assert set(r6["definitions"]) >= set(r6["denominators"])
    assert "held_out_recall_at_5_R4_ge_R0_minus_points" not in criteria["D1_hybrid_as_candidate_generator"]
    assert [amendment["section"] for amendment in config["amendments"]][:4] == [1288, 1290, 1370, 1436]


def test_run_offline_reports_r6_as_an_error_block_while_thresholds_are_unfixed(monkeypatch):
    import copy

    from code_intelligence.evaluation.e1 import run as run_module

    locked = copy.deepcopy(run_module.load_e1_config())
    locked["decision_criteria"]["R6"]["thresholds_fixed"] = False
    monkeypatch.setattr(run_module, "load_e1_config", lambda: locked)

    report = run_module.run_offline(["R6"], graph=_graph(), llm=_fixed("NONE"))

    block = report["systems"]["R6"]
    assert block["status"] == "error"
    assert "thresholds" in block["detail"]
    assert report["status"] == "partial"


def test_run_offline_keeps_the_arbitration_diagnostics_of_every_case(r4, tmp_path):
    import json

    from code_intelligence.evaluation.e1 import run as run_module
    from code_intelligence.evaluation.e1.cases import load_calibration_cases

    r4(["model:purchase.order", "model:sale.order"])
    output = tmp_path / "report.json"
    case_count = len(load_calibration_cases()[0])

    report = run_module.run_offline(["R6"], graph=_graph(), llm=_fixed("NONE"), output_path=output)

    rows = report["systems"]["R6"]["scores"]
    assert len(rows) == case_count
    assert {row["diagnostics"]["arbitration_status"] for row in rows} == {"NONE"}
    assert {row["diagnostics"]["raw_output"] for row in rows} == {"NONE"}
    stored = json.loads(output.read_text(encoding="utf-8"))
    stored_rows = stored["systems"]["R6"]["scores"]
    assert [row["diagnostics"]["arbitration_status"] for row in stored_rows] == ["NONE"] * case_count


def test_persist_report_accepts_diagnostics_that_are_not_plain_json(tmp_path):
    import json

    from code_intelligence.evaluation.e1.run import persist_report

    target = tmp_path / "report.json"
    persist_report({"systems": {"R6": {"scores": [{"diagnostics": {"seen": {"a", "b"}}}]}}}, target)

    stored = json.loads(target.read_text(encoding="utf-8"))
    assert "seen" in stored["systems"]["R6"]["scores"][0]["diagnostics"]


def test_rescore_keeps_stored_diagnostics_and_tolerates_rows_without_any():
    from code_intelligence.evaluation.e1.cases import load_calibration_cases
    from code_intelligence.evaluation.e1.rescore import rescore_report

    cases, digest, _ = load_calibration_cases()
    base = {
        "case_id": cases[0].case_id,
        "candidates": ["model:purchase.order"],
        "declared_ambiguous": False,
        "is_resolved": True,
    }
    report = {
        "cases_digest": digest,
        "systems": {
            "R6": {"status": "scored", "scores": [{**base, "diagnostics": {"arbitration_status": "CHOSEN"}}]},
            "R4": {"status": "scored", "scores": [base]},
        },
    }

    rescored = rescore_report(report, cases, None, cases_digest=digest)

    assert rescored["systems"]["R6"]["scores"][0]["diagnostics"] == {"arbitration_status": "CHOSEN"}
    assert "diagnostics" not in rescored["systems"]["R4"]["scores"][0]
