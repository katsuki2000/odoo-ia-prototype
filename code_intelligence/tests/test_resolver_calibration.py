from pathlib import Path
from types import SimpleNamespace

from code_intelligence.evaluation.e1.cases import DATA_DIR, load_calibration_cases
from code_intelligence.evaluation.resolver_calibration import (
    ABSTAINED_RIGHTLY,
    ABSTAINED_WRONGLY,
    CORRECT,
    WRONG,
    score_case,
    summarize,
)

ROLE_CASES = DATA_DIR / "role_calibration_cases.json"


def _concept(models, diagnostics=None):
    return SimpleNamespace(
        is_resolved=bool(models), resolved_models=list(models),
        source_step="hybrid_arbitration" if models else "unresolved", diagnostics=diagnostics or {},
    )


def _cases():
    cases, _digest, _meta = load_calibration_cases(ROLE_CASES)
    return {case.case_id: case for case in cases}


def test_role_cases_load_with_a_family_of_their_own_and_leave_the_e1_seed_alone():
    cases = _cases()
    assert len(cases) == 9
    assert {case.family for case in cases.values()} == {"role_question", "absent"}
    assert all(case.ground_truth["method"] == "odoo_oracle" for case in cases.values())
    assert all(case.ground_truth["reviewed_by_pmm"] == "false" for case in cases.values())
    seed, _digest, meta = load_calibration_cases()
    assert len(seed) == 8 and meta["status"] == "seed_incomplete"
    assert not {case.case_id for case in seed} & set(cases)


def test_role_cases_do_not_reuse_a_frozen_series_1_question():
    import json

    series = json.loads((Path(__file__).resolve().parents[1] / "evaluation" / "chat_series" / "data" / "series_1.json")
                        .read_text(encoding="utf-8"))
    frozen = {case["question"] for case in series["cases"]}
    assert not frozen & {case.question for case in _cases().values()}


def test_a_matching_model_is_correct_and_another_one_is_wrong():
    case = _cases()["role_fr_quotation_confirmer"]
    assert score_case(case, _concept(["sale.order"]))["verdict"] == CORRECT
    assert score_case(case, _concept(["purchase.order"]))["verdict"] == WRONG


def test_abstaining_on_a_positive_case_is_an_abstention_to_fault_and_keeps_the_raw_answer():
    case = _cases()["role_fr_expense_report_approver"]
    row = score_case(case, _concept([], {"arbitration_outcome": "none", "arbitration_raw": "NONE"}))
    assert row["verdict"] == ABSTAINED_WRONGLY
    assert row["arbitration_raw"] == "NONE"


def test_a_silent_choice_where_a_clarification_is_expected_is_wrong():
    case = _cases()["role_fr_absent_printer_repair"]
    assert score_case(case, _concept([]))["verdict"] == ABSTAINED_RIGHTLY
    assert score_case(case, _concept(["res.partner"]))["verdict"] == WRONG


def test_summary_counts_every_verdict_by_family():
    cases = _cases()
    rows = [
        score_case(cases["role_fr_quotation_confirmer"], _concept(["sale.order"])),
        score_case(cases["role_fr_expense_report_approver"], _concept([])),
        score_case(cases["role_fr_absent_printer_repair"], _concept([])),
    ]
    summary = summarize(rows)
    assert (summary["total"], summary[CORRECT], summary[ABSTAINED_WRONGLY], summary[ABSTAINED_RIGHTLY], summary[WRONG]) == (3, 1, 1, 1, 0)
    assert summary["by_family"]["role_question"] == {CORRECT: 1, ABSTAINED_WRONGLY: 1}
