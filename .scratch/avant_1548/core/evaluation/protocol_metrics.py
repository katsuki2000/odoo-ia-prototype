"""Deterministic scoring and pre-registered statistical verdict for the frozen evaluation protocol."""

from __future__ import annotations

import json
import random
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from core.evaluation.frozen_cases import SPLITS, ExpectedClaim, FrozenCase, FrozenDataset, require

OUTCOMES = ("answered", "clarification", "abstention", "refusal", "error")
# The system has no clarification output (section 1096): not guessing satisfies must_clarify.
CLARIFY_ACCEPTED = ("clarification", "abstention")
TECHNICAL_IDENTIFIER = re.compile(
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|\b[a-z]{2,}[a-z0-9]*(?:\.[a-z]{2,}[a-z0-9_]*)+\b"
)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    outcome: str
    answer: str = ""
    sources_used: tuple = ()
    resolved_objects: tuple = ()
    evidence: tuple = ()
    claims_total: int = 0
    unsupported_claims: int = 0

    @classmethod
    def from_dict(cls, data: Mapping) -> "CaseResult":
        result = cls(
            case_id=data["case_id"],
            outcome=data["outcome"],
            answer=data.get("answer", ""),
            sources_used=tuple(data.get("sources_used", ())),
            resolved_objects=tuple(data.get("resolved_objects", ())),
            evidence=tuple((row["kind"], row["source"]) for row in data.get("evidence", ())),
            claims_total=int(data.get("claims_total", 0)),
            unsupported_claims=int(data.get("unsupported_claims", 0)),
        )
        require(result.outcome in OUTCOMES, f"{result.case_id}: outcome must be one of {OUTCOMES}")
        require(0 <= result.unsupported_claims <= result.claims_total, f"{result.case_id}: inconsistent claim counts")
        return result


@dataclass(frozen=True)
class Preregistration:
    target_accuracy: float
    confidence: float
    resamples: int
    seed: int
    resolution_k: int
    min_instances: Optional[int]
    min_coverage: Optional[float]
    clarify_by_abstention_counts_as_correct: Optional[bool] = None

    @classmethod
    def load(cls, path: Path) -> "Preregistration":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    @property
    def complete(self) -> bool:
        return (
            self.min_instances is not None
            and self.min_coverage is not None
            and self.clarify_by_abstention_counts_as_correct is not None
        )


@dataclass(frozen=True)
class CaseScore:
    case: FrozenCase
    result: CaseResult
    correct: bool
    clarify_by_abstention: bool
    answered: bool
    wrong_tool: bool
    leaked: bool
    evidence_completeness: Optional[float]
    claim_recall: Optional[float]


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("\u2019", "'"))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def claim_matched(claim: ExpectedClaim, answer: str) -> bool:
    text = normalize(answer)
    return (
        all(normalize(term) in text for term in claim.all_of)
        and all(any(normalize(term) in text for term in group) for group in claim.any_of)
        and not any(normalize(term) in text for term in claim.none_of)
    )


def is_correct(case: FrozenCase, result: CaseResult) -> bool:
    if case.abstention_rule == "must_clarify":
        return result.outcome in CLARIFY_ACCEPTED
    if case.abstention_rule == "must_refuse_unauthorized":
        return result.outcome == "refusal"
    return result.outcome == "answered" and all(claim_matched(claim, result.answer) for claim in case.expected_claims)


def evidence_completeness(case: FrozenCase, result: CaseResult) -> Optional[float]:
    if not case.acceptable_evidence:
        return None
    collected = set(result.evidence)
    found = sum((spec.kind, spec.source) in collected for spec in case.acceptable_evidence)
    return found / len(case.acceptable_evidence)


def claim_recall(case: FrozenCase, result: CaseResult) -> Optional[float]:
    if "internal_docs" not in case.expected_sources or not case.expected_claims:
        return None
    if result.outcome != "answered":
        return 0.0
    return sum(claim_matched(claim, result.answer) for claim in case.expected_claims) / len(case.expected_claims)


def score_case(case: FrozenCase, result: CaseResult) -> CaseScore:
    answered = result.outcome == "answered"
    return CaseScore(
        case=case,
        result=result,
        correct=is_correct(case, result),
        clarify_by_abstention=case.abstention_rule == "must_clarify" and result.outcome == "abstention",
        answered=answered,
        wrong_tool=bool(set(result.sources_used) - set(case.expected_sources)),
        leaked=answered and TECHNICAL_IDENTIFIER.search(result.answer) is not None,
        evidence_completeness=evidence_completeness(case, result),
        claim_recall=claim_recall(case, result),
    )


def strict_correct(score: CaseScore) -> bool:
    return score.correct and not score.clarify_by_abstention


def ratio(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator else None


def coverage(scores: Sequence[CaseScore]) -> Optional[float]:
    expected = [score for score in scores if score.case.abstention_rule == "none"]
    return ratio(sum(score.answered for score in expected), len(expected))


def resolution_recall(scores: Sequence[CaseScore], k: int) -> Optional[float]:
    rows = [score for score in scores if score.case.expected_objects]
    recalls = [
        len(set(score.case.expected_objects) & set(score.result.resolved_objects[:k])) / len(score.case.expected_objects)
        for score in rows
    ]
    return ratio(sum(recalls), len(recalls))


def mean_completeness(scores: Sequence[CaseScore]) -> Optional[float]:
    values = [score.evidence_completeness for score in scores if score.evidence_completeness is not None]
    return ratio(sum(values), len(values))


def mean_claim_recall(scores: Sequence[CaseScore]) -> Optional[float]:
    values = [score.claim_recall for score in scores if score.claim_recall is not None]
    return ratio(sum(values), len(values))


def human_acceptance(scores: Sequence[CaseScore], ratings: Optional[Mapping[str, bool]]) -> tuple:
    rated = [ratings[score.case.case_id] for score in scores if ratings and score.case.case_id in ratings]
    return ratio(sum(rated), len(rated)), len(rated)


def aggregate(scores: Sequence[CaseScore], k: int, ratings: Optional[Mapping[str, bool]] = None) -> dict:
    answered = [score for score in scores if score.answered]
    claims_total = sum(score.result.claims_total for score in scores)
    unsupported = sum(score.result.unsupported_claims for score in scores)
    unsupported_rate = ratio(unsupported, claims_total)
    acceptance, rated = human_acceptance(scores, ratings)
    return {
        "cases": len(scores),
        "accuracy_all_questions": ratio(sum(score.correct for score in scores), len(scores)),
        "accuracy_all_questions_strict": ratio(sum(strict_correct(score) for score in scores), len(scores)),
        "clarify_by_abstention_cases": sum(score.clarify_by_abstention for score in scores),
        "accuracy_answered_questions": ratio(sum(score.correct for score in answered), len(answered)),
        "coverage": coverage(scores),
        "unsupported_claim_rate": unsupported_rate,
        "answer_faithfulness": None if unsupported_rate is None else 1 - unsupported_rate,
        "wrong_tool_rate": ratio(sum(score.wrong_tool for score in scores), len(scores)),
        "technical_identifier_leak_rate": ratio(sum(score.leaked for score in answered), len(answered)),
        "resolution_recall_at_k": resolution_recall(scores, k),
        "evidence_completeness": mean_completeness(scores),
        "claim_recall_documentary": mean_claim_recall(scores),
        "human_business_acceptance_rate": acceptance,
        "human_rated_cases": rated,
    }


def breakdown(scores: Sequence[CaseScore], key) -> dict:
    groups: dict = {}
    for score in scores:
        groups.setdefault(key(score.case), []).append(score)
    return {
        name: {"cases": len(rows), "accuracy_all_questions": ratio(sum(row.correct for row in rows), len(rows))}
        for name, rows in sorted(groups.items())
    }


def cluster_bootstrap_interval(
    outcomes_by_instance: Mapping[str, Sequence[int]], resamples: int, confidence: float, seed: int,
) -> tuple:
    rng = random.Random(seed)
    names = sorted(outcomes_by_instance)
    estimates = []
    for _ in range(resamples):
        hits = total = 0
        for name in (rng.choice(names) for _ in names):
            cases = outcomes_by_instance[name]
            sample = [cases[rng.randrange(len(cases))] for _ in cases]
            hits += sum(sample)
            total += len(sample)
        estimates.append(hits / total)
    estimates.sort()
    tail = (1 - confidence) / 2
    return estimates[int(tail * resamples)], estimates[min(resamples - 1, int((1 - tail) * resamples))]


def verdict(scores: Sequence[CaseScore], prereg: Preregistration) -> dict:
    if not scores:
        return {"verdict": "no_cases", "interval": None, "instances": 0}
    lenient = prereg.clarify_by_abstention_counts_as_correct is not False
    by_instance: dict = {}
    for score in scores:
        by_instance.setdefault(score.case.instance, []).append(int(score.correct if lenient else strict_correct(score)))
    interval = cluster_bootstrap_interval(by_instance, prereg.resamples, prereg.confidence, prereg.seed)
    answered_share = coverage(scores)
    if not prereg.complete:
        outcome = "preregistration_incomplete"
    elif len(by_instance) < prereg.min_instances:
        outcome = "inconclusive_too_few_instances"
    elif (answered_share or 0) < prereg.min_coverage:
        outcome = "fail_coverage"
    else:
        outcome = "pass" if interval[0] >= prereg.target_accuracy else "fail"
    return {
        "verdict": outcome,
        "interval": list(interval),
        "instances": len(by_instance),
        "basis": "abstention_counts_for_must_clarify" if lenient else "strict",
    }


def evaluate(
    dataset: FrozenDataset,
    results: Iterable[CaseResult],
    prereg: Preregistration,
    human_ratings: Optional[Mapping[str, bool]] = None,
) -> dict:
    by_id = {result.case_id: result for result in results}
    unknown = sorted(set(by_id) - {case.case_id for case in dataset.cases})
    require(not unknown, f"results for unknown cases: {unknown}")
    missing = sorted(case.case_id for case in dataset.cases if case.case_id not in by_id)
    scores = [
        score_case(case, by_id.get(case.case_id, CaseResult(case.case_id, "error")))
        for case in dataset.cases
    ]
    report = {
        "dataset": {"version": dataset.version, "digest": dataset.digest},
        "preregistration": asdict(prereg),
        "missing_results": missing,
        "splits": {},
    }
    for split in SPLITS:
        rows = [score for score in scores if score.case.split == split]
        section = {
            "metrics": aggregate(rows, prereg.resolution_k, human_ratings),
            "by_instance": breakdown(rows, lambda case: case.instance),
            "by_module": breakdown(rows, lambda case: case.module),
            "by_language": breakdown(rows, lambda case: case.user_context.language),
            "by_intent": breakdown(rows, lambda case: case.expected_intent),
        }
        if split == "held_out":
            section["statistics"] = verdict(rows, prereg)
        report["splits"][split] = section
    return report
