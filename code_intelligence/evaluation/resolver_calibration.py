"""Score the production concept resolver on calibration cases (no change to the resolver)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from code_intelligence.evaluation.e1.cases import E1Case

CORRECT = "juste"
WRONG = "faux"
ABSTAINED_WRONGLY = "abstention_a_tort"
ABSTAINED_RIGHTLY = "abstention_juste"
VERDICTS = (CORRECT, WRONG, ABSTAINED_WRONGLY, ABSTAINED_RIGHTLY)


def score_case(case: E1Case, concept: Any) -> dict[str, Any]:
    """Verdict for one case; a silent choice where a clarification was expected counts as wrong."""
    expected = [ref.removeprefix("model:") for ref in case.expected_objects if ref.startswith("model:")]
    chosen = list(concept.resolved_models) if concept.is_resolved else []
    if case.abstention_rule == "must_clarify":
        verdict = WRONG if concept.is_resolved else ABSTAINED_RIGHTLY
    elif not concept.is_resolved:
        verdict = ABSTAINED_WRONGLY
    else:
        verdict = CORRECT if chosen == expected else WRONG
    diagnostics = dict(getattr(concept, "diagnostics", None) or {})
    return {
        "case_id": case.case_id,
        "family": case.family,
        "language": case.language,
        "question": case.question,
        "expected": expected,
        "chosen": chosen,
        "source_step": concept.source_step,
        "verdict": verdict,
        "arbitration_outcome": diagnostics.get("arbitration_outcome"),
        "arbitration_raw": diagnostics.get("arbitration_raw"),
        "ambiguous_candidates": diagnostics.get("ambiguous_candidates"),
    }


def summarize(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    counts = Counter(row["verdict"] for row in rows)
    by_family: dict[str, Counter] = {}
    for row in rows:
        by_family.setdefault(row["family"], Counter())[row["verdict"]] += 1
    return {
        "total": len(rows),
        **{verdict: counts.get(verdict, 0) for verdict in VERDICTS},
        "by_family": {family: dict(counter) for family, counter in sorted(by_family.items())},
    }


__all__ = ["score_case", "summarize", "VERDICTS", "CORRECT", "WRONG", "ABSTAINED_WRONGLY", "ABSTAINED_RIGHTLY"]
