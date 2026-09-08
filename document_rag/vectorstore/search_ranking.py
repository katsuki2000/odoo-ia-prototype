"""
Ranking and Fusion Module — Reciprocal Rank Fusion (RRF) & Cross-Encoder Re-ranking.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

_cross_encoder_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_cross_encoder_instance = None


def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
    k: int = 60,
    relevance_threshold: float = 0.3,
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


def _get_cross_encoder():
    """Load and cache the local cross-encoder model (lazy singleton)."""
    global _cross_encoder_instance
    if _cross_encoder_instance is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading local cross-encoder model: %s", _cross_encoder_model_name)
        try:
            _cross_encoder_instance = CrossEncoder(_cross_encoder_model_name, local_files_only=True)
        except Exception as e:
            logger.warning("Failed to load CrossEncoder in offline mode, retrying online: %s", e)
            _cross_encoder_instance = CrossEncoder(_cross_encoder_model_name)
    return _cross_encoder_instance


def cross_encoder_rerank(
    query: str,
    results: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Rerank search results using a local cross-encoder model."""
    if not results:
        return []

    try:
        search_mod = sys.modules.get("document_rag.vectorstore.search")
        getter = getattr(search_mod, "_get_cross_encoder", _get_cross_encoder) if search_mod else _get_cross_encoder
        model = getter()
        if model is None:
            return results[:top_k]

        pairs = [[query, r["document"][:1500]] for r in results]
        scores = model.predict(pairs)

        for i, r in enumerate(results):
            r["cross_encoder_score"] = float(scores[i])

        results.sort(key=lambda x: x["cross_encoder_score"], reverse=True)

    except Exception as e:
        logger.error("Local cross-encoder reranking failed: %s", e)
        logger.info("Falling back to hybrid search scores.")
        return results[:top_k]

    return results[:top_k]
