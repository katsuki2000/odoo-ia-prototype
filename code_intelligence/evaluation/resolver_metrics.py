"""Metrics for frozen, instance-aware evaluation runs."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Mapping


def _wilson_lower_bound(successes: int, total: int, z: float = 1.959963984540054) -> float | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (center - margin) / denominator)


def summarize_evaluation(rows: Iterable[Mapping[str, object]]) -> dict:
    rows = list(rows)
    total = len(rows)
    answered = [row for row in rows if row.get("answered") is True]
    correct = sum(row.get("correct") is True for row in rows)
    answered_correct = sum(row.get("correct") is True for row in answered)
    tool_rows = [row for row in rows if row.get("wrong_tool") is not None]
    claim_count = sum(int(row.get("claim_count", 0) or 0) for row in rows)
    unsupported_count = sum(int(row.get("unsupported_claims", 0) or 0) for row in rows)
    leak_rows = [row for row in rows if row.get("user_output") is not None]
    leak_count = sum(int(row.get("technical_identifier_leaks", 0) or 0) for row in leak_rows)
    technical_tokens = sum(int(row.get("technical_identifier_count", 0) or 0) for row in leak_rows)
    candidate_rows = [
        row for row in rows if row.get("candidate_domain_evaluable") is True
    ]
    candidate_recall = {
        f"candidate_domain_recall_at_{cutoff}": (
            sum(
                isinstance(row.get("candidate_domain_rank"), int)
                and row["candidate_domain_rank"] <= cutoff
                for row in candidate_rows
            ) / len(candidate_rows)
            if candidate_rows else None
        )
        for cutoff in (1, 3, 5)
    }

    by_instance = defaultdict(list)
    for row in rows:
        by_instance[str(row.get("instance_id") or "unspecified")].append(row)
    cluster_accuracy = {
        instance: sum(item.get("correct") is True for item in items) / len(items)
        for instance, items in sorted(by_instance.items()) if items
    }

    return {
        "total_questions": total,
        "answered_questions": len(answered),
        "accuracy_all_questions": correct / total if total else None,
        "accuracy_answered_questions": answered_correct / len(answered) if answered else None,
        "coverage": len(answered) / total if total else None,
        "wilson_lower_bound_95_pooled": _wilson_lower_bound(correct, total),
        "instance_count": len(by_instance),
        "accuracy_by_instance": cluster_accuracy,
        "cluster_confidence_interval": None if len(by_instance) < 2 else "requires instance-level bootstrap",
        "candidate_domain_questions": len(candidate_rows),
        **candidate_recall,
        "wrong_tool_rate": (
            sum(row.get("wrong_tool") is True for row in tool_rows) / len(tool_rows)
            if tool_rows else None
        ),
        "unsupported_claim_rate": unsupported_count / claim_count if claim_count else None,
        "technical_identifier_leak_rate": leak_count / technical_tokens if technical_tokens else None,
        "metric_denominators": {
            "wrong_tool_questions": len(tool_rows),
            "claims": claim_count,
            "user_output_rows": len(leak_rows),
            "technical_identifiers": technical_tokens,
        },
    }


__all__ = ["summarize_evaluation"]
