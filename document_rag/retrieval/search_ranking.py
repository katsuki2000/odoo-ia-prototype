"""
Ranking and Fusion Module — Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

from typing import Any
from config.settings import RAG_BM25_WEIGHT, RAG_RELEVANCE_THRESHOLD, RAG_VECTOR_WEIGHT


def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    vector_weight: float = RAG_VECTOR_WEIGHT,
    bm25_weight: float = RAG_BM25_WEIGHT,
    k: int = 60,
    relevance_threshold: float = RAG_RELEVANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion (RRF) combining vector and BM25 search results.
    Formula: RRF_score(d) = w_v / (k + rank_v(d)) + w_b / (k + rank_b(d))
    """
    doc_map: dict[str, dict[str, Any]] = {}
    rrf_scores: dict[str, float] = {}

    for rank, result in enumerate(vector_results):
        doc_id = result["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + vector_weight / (k + rank + 1)
        if doc_id not in doc_map:
            doc_map[doc_id] = result

    for rank, result in enumerate(bm25_results):
        doc_id = result["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + bm25_weight / (k + rank + 1)
        if doc_id not in doc_map:
            doc_map[doc_id] = result

    if rrf_scores:
        max_score = max(rrf_scores.values())
        if max_score > 0:
            rrf_scores = {
                doc_id: score / max_score
                for doc_id, score in rrf_scores.items()
            }

    fused = []
    for doc_id, score in rrf_scores.items():
        if score >= relevance_threshold:
            result = doc_map[doc_id].copy()
            result["rrf_score"] = score
            fused.append(result)

    fused.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused
