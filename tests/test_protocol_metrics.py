"""Hermetic tests for the protocol metrics engine."""

from pathlib import Path

import pytest

from core.evaluation import frozen_cases as fc
from core.evaluation import protocol_metrics as pm
from tests.frozen_case_samples import make_case

PREREG = pm.Preregistration(0.8, 0.95, 200, 1, 2, 2, 0.5, True)


def dataset(*rows) -> fc.FrozenDataset:
    return fc.dataset_from_payload(fc.freeze_dataset(rows, 1))


GOOD = "A sales manager can read a quotation."


def answered(case_id="c1", answer=GOOD, **extra) -> pm.CaseResult:
    return pm.CaseResult(case_id, "answered", answer, **extra)


def test_claim_matching_is_accent_and_case_insensitive():
    claim = fc.ExpectedClaim("c", "s", all_of=("Équipe",), any_of=(("lire", "read"),), none_of=("cannot",))
    assert pm.claim_matched(claim, "L'EQUIPE peut lire")
    assert not pm.claim_matched(claim, "equipe cannot read")
    assert not pm.claim_matched(claim, "equipe sans rapport")


def test_correctness_by_abstention_rule():
    answer_case = fc.FrozenCase.from_dict(make_case())
    assert pm.is_correct(answer_case, answered())
    assert not pm.is_correct(answer_case, answered(answer="unrelated"))
    assert not pm.is_correct(answer_case, pm.CaseResult("c1", "clarification"))
    clarify = fc.FrozenCase.from_dict(make_case(abstention_rule="must_clarify", expected_claims=[], acceptable_evidence=[]))
    assert pm.is_correct(clarify, pm.CaseResult("c1", "clarification"))
    assert pm.is_correct(clarify, pm.CaseResult("c1", "abstention"))
    assert not pm.is_correct(clarify, answered())
    assert not pm.is_correct(clarify, pm.CaseResult("c1", "refusal"))
    assert not pm.is_correct(clarify, pm.CaseResult("c1", "error"))
    assert not pm.is_correct(answer_case, pm.CaseResult("c1", "abstention"))
    refuse = fc.FrozenCase.from_dict(make_case(abstention_rule="must_refuse_unauthorized", expected_claims=[], acceptable_evidence=[]))
    assert pm.is_correct(refuse, pm.CaseResult("c1", "refusal"))


def test_aggregate_metrics():
    data = dataset(make_case("a"), make_case("b"), make_case("c"))
    results = [
        answered("a", evidence=(("graph", "model:sale.order"),), sources_used=("code",),
                 resolved_objects=("model:sale.order",), claims_total=2, unsupported_claims=0),
        answered("b", answer="wrong_field_name leaked", sources_used=("runtime",), claims_total=2, unsupported_claims=1),
        pm.CaseResult("c", "clarification"),
    ]
    scores = [pm.score_case(case, next(r for r in results if r.case_id == case.case_id)) for case in data.cases]
    metrics = pm.aggregate(scores, k=2)
    assert metrics["accuracy_all_questions"] == pytest.approx(1 / 3)
    assert metrics["accuracy_answered_questions"] == pytest.approx(1 / 2)
    assert metrics["coverage"] == pytest.approx(2 / 3)
    assert metrics["unsupported_claim_rate"] == pytest.approx(1 / 4)
    assert metrics["answer_faithfulness"] == pytest.approx(3 / 4)
    assert metrics["wrong_tool_rate"] == pytest.approx(1 / 3)
    assert metrics["technical_identifier_leak_rate"] == pytest.approx(1 / 2)
    assert metrics["resolution_recall_at_k"] == pytest.approx((1 / 2 + 0 + 0) / 3)
    assert metrics["evidence_completeness"] == pytest.approx(1 / 3)
    assert metrics["human_business_acceptance_rate"] is None


def test_human_acceptance_uses_only_rated_cases():
    data = dataset(make_case("a"), make_case("b"))
    scores = [pm.score_case(case, answered(case.case_id)) for case in data.cases]
    metrics = pm.aggregate(scores, k=1, ratings={"a": True})
    assert metrics["human_business_acceptance_rate"] == 1.0
    assert metrics["human_rated_cases"] == 1


def test_technical_identifier_detection():
    assert pm.TECHNICAL_IDENTIFIER.search("see sale.order now")
    assert pm.TECHNICAL_IDENTIFIER.search("field amount_total")
    assert not pm.TECHNICAL_IDENTIFIER.search("e.g. a quotation, i.e. an offer")


def test_bootstrap_is_deterministic_and_ordered():
    outcomes = {"x": [1, 1, 0, 1], "y": [1, 1, 1, 1], "z": [0, 1, 1, 1]}
    first = pm.cluster_bootstrap_interval(outcomes, 300, 0.95, 5)
    assert first == pm.cluster_bootstrap_interval(outcomes, 300, 0.95, 5)
    assert 0 <= first[0] <= first[1] <= 1


def scores_for(instances: dict) -> list:
    rows = [
        make_case(f"{name}_{index}", instance=name, split="held_out")
        for name, flags in instances.items() for index, _ in enumerate(flags)
    ]
    data = fc.dataset_from_payload(fc.freeze_dataset(rows, 1))
    flags = {f"{name}_{index}": flag for name, values in instances.items() for index, flag in enumerate(values)}
    return [
        pm.score_case(case, answered(case.case_id, GOOD if flags[case.case_id] else "nope"))
        for case in data.cases
    ]


def test_verdict_states():
    perfect = scores_for({"a": [1] * 10, "b": [1] * 10, "c": [1] * 10})
    assert pm.verdict(perfect, PREREG)["verdict"] == "pass"
    assert pm.verdict(perfect, pm.Preregistration(0.8, 0.95, 200, 1, 2, None, None))["verdict"] == "preregistration_incomplete"
    assert pm.verdict(perfect, pm.Preregistration(0.8, 0.95, 200, 1, 2, 5, 0.5, True))["verdict"] == "inconclusive_too_few_instances"
    weak = scores_for({"a": [1, 0] * 5, "b": [0] * 10, "c": [1, 0] * 5})
    assert pm.verdict(weak, PREREG)["verdict"] == "fail"
    assert pm.verdict([], PREREG)["verdict"] == "no_cases"


def test_verdict_fail_coverage():
    rows = [make_case(f"k{i}", instance="a", split="held_out") for i in range(4)] + [
        make_case(f"m{i}", instance="b", split="held_out") for i in range(4)
    ]
    data = fc.dataset_from_payload(fc.freeze_dataset(rows, 1))
    scores = [pm.score_case(case, pm.CaseResult(case.case_id, "clarification")) for case in data.cases]
    assert pm.verdict(scores, PREREG)["verdict"] == "fail_coverage"


def test_coverage_only_counts_cases_that_expect_an_answer():
    rows = [make_case(f"a{i}", instance="a" if i % 2 else "b") for i in range(8)] + [
        make_case(f"k{i}", instance="a" if i % 2 else "b", abstention_rule="must_clarify",
                  expected_claims=[], acceptable_evidence=[]) for i in range(4)
    ]
    data = fc.dataset_from_payload(fc.freeze_dataset(rows, 1))
    results = {case.case_id: answered(case.case_id) if case.abstention_rule == "none"
               else pm.CaseResult(case.case_id, "clarification") for case in data.cases}
    scores = [pm.score_case(case, results[case.case_id]) for case in data.cases]
    assert pm.aggregate(scores, k=2)["coverage"] == 1.0
    assert pm.verdict(scores, pm.Preregistration(0.8, 0.95, 200, 1, 2, 2, 0.8, False))["verdict"] != "fail_coverage"
    silent = [pm.score_case(case, pm.CaseResult(case.case_id, "abstention")) for case in data.cases]
    assert pm.aggregate(silent, k=2)["coverage"] == 0.0


def test_evaluate_reports_missing_results_and_rejects_unknown():
    data = dataset(make_case("a"), make_case("b", split="calibration", instance="adversarial_custom"))
    report = pm.evaluate(data, [answered("a")], PREREG)
    assert report["missing_results"] == ["b"]
    assert report["splits"]["held_out"]["metrics"]["accuracy_all_questions"] == 1.0
    assert report["splits"]["calibration"]["metrics"]["accuracy_all_questions"] == 0.0
    assert "statistics" in report["splits"]["held_out"] and "statistics" not in report["splits"]["calibration"]
    with pytest.raises(ValueError):
        pm.evaluate(data, [answered("ghost")], PREREG)


def test_result_validation():
    with pytest.raises(ValueError):
        pm.CaseResult.from_dict({"case_id": "a", "outcome": "maybe"})
    with pytest.raises(ValueError):
        pm.CaseResult.from_dict({"case_id": "a", "outcome": "answered", "claims_total": 1, "unsupported_claims": 2})


def test_shipped_preregistration_is_complete_and_pinned():
    path = Path(__file__).resolve().parent.parent / "core" / "evaluation" / "protocol" / "preregistration.json"
    prereg = pm.Preregistration.load(path)
    assert prereg.complete
    assert (prereg.target_accuracy, prereg.confidence) == (0.8, 0.95)
    assert (prereg.min_instances, prereg.min_coverage) == (6, 0.8)
    assert prereg.clarify_by_abstention_counts_as_correct is False


def test_clarify_by_abstention_is_reported_and_excluded_from_strict_accuracy():
    clarify = make_case("k", abstention_rule="must_clarify", expected_claims=[], acceptable_evidence=[])
    data = dataset(make_case("a"), clarify)
    results = [answered("a"), pm.CaseResult("k", "abstention")]
    scores = [pm.score_case(case, next(r for r in results if r.case_id == case.case_id)) for case in data.cases]
    metrics = pm.aggregate(scores, k=2)
    assert metrics["accuracy_all_questions"] == 1.0
    assert metrics["accuracy_all_questions_strict"] == 0.5
    assert metrics["clarify_by_abstention_cases"] == 1
    clarified = pm.score_case(data.cases[1], pm.CaseResult("k", "clarification"))
    assert not clarified.clarify_by_abstention and pm.strict_correct(clarified)


def test_verdict_basis_follows_the_preregistered_choice():
    rows = [make_case(f"k{i}", instance="a", abstention_rule="must_clarify", expected_claims=[], acceptable_evidence=[])
            for i in range(4)] + [make_case(f"m{i}", instance="b", abstention_rule="must_clarify",
                                            expected_claims=[], acceptable_evidence=[]) for i in range(4)]
    data = fc.dataset_from_payload(fc.freeze_dataset(rows, 1))
    scores = [pm.score_case(case, pm.CaseResult(case.case_id, "abstention")) for case in data.cases]
    lenient = pm.Preregistration(0.8, 0.95, 200, 1, 2, 2, 0.0, True)
    strict = pm.Preregistration(0.8, 0.95, 200, 1, 2, 2, 0.0, False)
    assert pm.verdict(scores, lenient) == {**pm.verdict(scores, lenient), "verdict": "pass", "basis": "abstention_counts_for_must_clarify"}
    assert pm.verdict(scores, strict)["verdict"] == "fail" and pm.verdict(scores, strict)["basis"] == "strict"
    assert pm.verdict(scores, pm.Preregistration(0.8, 0.95, 200, 1, 2, 2, 0.0))["verdict"] == "preregistration_incomplete"


def test_typographic_apostrophe_matches_plain_apostrophe():
    claim = fc.ExpectedClaim.from_dict({"claim_id": "c", "statement": "s", "all_of": ["pas d'accès"]})
    assert pm.claim_matched(claim, "Vous n\u2019avez pas d\u2019accès à ce modèle")
    assert pm.claim_matched(claim, "vous n'avez pas d'accès")
