"""Resolution metrics for E1 (offline, no LLM)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .cases import E1Case
from .projection import project_candidates

RECALL_KS = (1, 5, 10)
RAW_SUFFIX = "_raw"


def _normalize_ref(value: str) -> str:
    text = str(value).strip()
    if not text:
        return text
    if ":" in text:
        return text
    return f"model:{text}"


def _expected_refs(case: E1Case) -> set[str]:
    return {_normalize_ref(ref) for ref in case.expected_objects}


def _targets_models(expected: set[str]) -> bool:
    return bool(expected) and all(ref.startswith("model:") for ref in expected)


def _rank_metrics(
    case: E1Case,
    expected: set[str],
    ranked: Sequence[str],
    *,
    declared_ambiguous: bool,
    is_resolved: bool,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        f"recall_at_{k}": (expected <= set(ranked[:k])) if expected else None for k in RECALL_KS
    }
    metrics["silent_false_resolution"] = bool(
        case.abstention_rule == "none"
        and expected
        and ranked
        and is_resolved
        and ranked[0] not in expected
        and not declared_ambiguous
    )
    return metrics


def score_resolution_case(
    case: E1Case,
    *,
    candidates: Sequence[str],
    declared_ambiguous: bool = False,
    is_resolved: bool = True,
    primary_k: int = 5,
    projector: Optional[Callable[[str], Sequence[str]]] = None,
) -> dict[str, Any]:
    """Score one system output against one calibration case.

    When the case expects models and a projector is given, every candidate is first
    replaced by the model it belongs to; the metrics on the raw list stay available
    under the ``_raw`` suffix.
    """
    expected = _expected_refs(case)
    candidate_list = [_normalize_ref(name) for name in candidates if name]
    outcome = {"declared_ambiguous": declared_ambiguous, "is_resolved": is_resolved}
    raw = _rank_metrics(case, expected, candidate_list, **outcome)

    projected_list = None
    decision = raw
    if projector is not None and _targets_models(expected):
        projected_list = project_candidates(candidate_list, projector)
        decision = _rank_metrics(case, expected, projected_list, **outcome)

    if case.abstention_rule == "must_clarify":
        clarify_ok = (
            declared_ambiguous
            or len(set(candidate_list)) >= 2
            or (not candidate_list and not is_resolved)
        )
        resolved_ok = clarify_ok
    else:
        clarify_ok = None
        resolved_ok = bool(decision.get(f"recall_at_{primary_k}"))

    return {
        "case_id": case.case_id,
        "family": case.family,
        "abstention_rule": case.abstention_rule,
        "candidates": candidate_list,
        "projected_candidates": projected_list,
        "expected_objects": list(case.expected_objects),
        "declared_ambiguous": declared_ambiguous,
        "is_resolved": is_resolved,
        "clarify_correct": clarify_ok,
        "correct_at_primary_k": resolved_ok,
        **decision,
        **{f"{key}{RAW_SUFFIX}": value for key, value in raw.items()},
    }


def _rate(items: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    usable = [item for item in items if item.get(key) is not None]
    if not usable:
        return None
    return sum(bool(item.get(key)) for item in usable) / len(usable)


def _summarize(items: Sequence[Mapping[str, Any]], primary_k: int) -> dict[str, Any]:
    recall_key = f"recall_at_{primary_k}"
    return {
        "n": len(items),
        recall_key: _rate(items, recall_key),
        f"{recall_key}{RAW_SUFFIX}": _rate(items, f"{recall_key}{RAW_SUFFIX}"),
        "silent_false_rate": _rate(items, "silent_false_resolution"),
        f"silent_false_rate{RAW_SUFFIX}": _rate(items, f"silent_false_resolution{RAW_SUFFIX}"),
        "clarify_correct_rate": _rate(items, "clarify_correct"),
    }


def summarize_system_scores(
    scores: Iterable[Mapping[str, Any]],
    *,
    primary_k: int = 5,
) -> dict[str, Any]:
    rows = list(scores)
    by_family: dict[str, list] = defaultdict(list)
    for row in rows:
        by_family[str(row.get("family"))].append(row)
    return {
        **_summarize(rows, primary_k),
        "correct_at_primary_k_rate": _rate(rows, "correct_at_primary_k"),
        "by_family": {
            family: _summarize(items, primary_k) for family, items in sorted(by_family.items())
        },
    }
