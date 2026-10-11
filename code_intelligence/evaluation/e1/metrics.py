"""Resolution metrics for E1 (offline, no LLM)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Optional, Sequence

from .cases import E1Case


def _normalize_ref(value: str) -> str:
    text = str(value).strip()
    if not text:
        return text
    if ":" in text:
        return text
    return f"model:{text}"


def _expected_refs(case: E1Case) -> set[str]:
    return {_normalize_ref(ref) for ref in case.expected_objects}


def score_resolution_case(
    case: E1Case,
    *,
    candidates: Sequence[str],
    declared_ambiguous: bool = False,
    is_resolved: bool = True,
    primary_k: int = 5,
) -> dict[str, Any]:
    """Score one system output against one calibration case."""
    expected = _expected_refs(case)
    candidate_list = [_normalize_ref(name) for name in candidates if name]
    hit_at: dict[str, Optional[bool]] = {}
    for k in (1, 5, 10):
        if not expected:
            hit_at[f"recall_at_{k}"] = None
        else:
            hit_at[f"recall_at_{k}"] = expected <= set(candidate_list[:k])

    silent_false = False
    if case.abstention_rule == "none" and expected and candidate_list and is_resolved:
        silent_false = candidate_list[0] not in expected and not declared_ambiguous

    if case.abstention_rule == "must_clarify":
        clarify_ok = (
            declared_ambiguous
            or len(set(candidate_list)) >= 2
            or (not candidate_list and not is_resolved)
        )
        resolved_ok = clarify_ok
    else:
        clarify_ok = None
        resolved_ok = bool(hit_at.get(f"recall_at_{primary_k}"))

    return {
        "case_id": case.case_id,
        "family": case.family,
        "abstention_rule": case.abstention_rule,
        "candidates": candidate_list,
        "expected_objects": list(case.expected_objects),
        "declared_ambiguous": declared_ambiguous,
        "is_resolved": is_resolved,
        "silent_false_resolution": silent_false,
        "clarify_correct": clarify_ok,
        "correct_at_primary_k": resolved_ok,
        **hit_at,
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

    def rate(items: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
        usable = [item for item in items if item.get(key) is not None]
        if not usable:
            return None
        return sum(bool(item.get(key)) for item in usable) / len(usable)

    family_summary = {
        family: {
            "n": len(items),
            f"recall_at_{primary_k}": rate(items, f"recall_at_{primary_k}"),
            "silent_false_rate": rate(items, "silent_false_resolution"),
            "clarify_correct_rate": rate(items, "clarify_correct"),
        }
        for family, items in sorted(by_family.items())
    }
    return {
        "n": len(rows),
        f"recall_at_{primary_k}": rate(rows, f"recall_at_{primary_k}"),
        "silent_false_rate": rate(rows, "silent_false_resolution"),
        "clarify_correct_rate": rate(rows, "clarify_correct"),
        "correct_at_primary_k_rate": rate(rows, "correct_at_primary_k"),
        "by_family": family_summary,
    }
