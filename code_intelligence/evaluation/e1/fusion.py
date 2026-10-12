"""Reciprocal rank fusion of ranked candidate lists."""

from __future__ import annotations

from typing import Mapping, Sequence


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]],
    *,
    weights: Mapping[str, float] | None = None,
    constant: int = 60,
) -> list[tuple[str, float]]:
    """Fuse ranked lists into one list ordered by weighted ``1 / (constant + rank)`` sums.

    Ranks start at 1. Ties fall back to the best individual rank, then to the
    reference itself, so the order never depends on dict or set iteration.
    """
    if constant < 0:
        raise ValueError("constant must be non-negative")

    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for source, ranked in rankings.items():
        weight = 1.0 if weights is None else float(weights.get(source, 1.0))
        seen: set[str] = set()
        rank = 0
        for ref in ranked:
            if ref in seen:
                continue
            seen.add(ref)
            rank += 1
            scores[ref] = scores.get(ref, 0.0) + weight / (constant + rank)
            best_rank[ref] = min(best_rank.get(ref, rank), rank)

    return sorted(scores.items(), key=lambda item: (-item[1], best_rank[item[0]], item[0]))
