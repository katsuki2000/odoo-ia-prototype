"""
Hybrid Search Module — Vector Search (ChromaDB) and Hybrid Combination.
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import VECTOR_SIMILARITY_FLOOR
from document_rag.vectorstore.bm25_index import BM25Index, bm25_search
from document_rag.vectorstore.chroma_manager import ChromaManager
from document_rag.vectorstore.search_ranking import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


def vector_search(
    chroma_manager: ChromaManager | list[ChromaManager],
    query: str,
    top_k: int = 12,
    where: dict[str, Any] | None = None,
    min_similarity: float = VECTOR_SIMILARITY_FLOOR,
) -> list[dict[str, Any]]:
    """
    Vector similarity search via ChromaDB using cosine similarity.
    Filters out results below min_similarity before returning.
    """
    managers = chroma_manager if isinstance(chroma_manager, list) else [chroma_manager]

    results: list[dict[str, Any]] = []
    for manager in managers:
        try:
            raw = manager.query(query_text=query, top_k=top_k, where=where)
        except Exception as e:
            logger.error(
                "Vector search failed on collection '%s': %s",
                getattr(manager.collection, "name", "?"), e
            )
            continue
        for item in raw.get("results", []):
            if item["similarity"] < min_similarity:
                continue
            results.append({
                "id": item["id"],
                "document": item["document"],
                "metadata": item["metadata"],
                "score": item["similarity"],
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def hybrid_search(
    chroma_manager: ChromaManager | list[ChromaManager],
    bm25_index: BM25Index,
    query: str,
    top_k: int = 12,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
    relevance_threshold: float = 0.3,
    min_similarity: float = VECTOR_SIMILARITY_FLOOR,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search combining vector similarity and BM25 keyword matching via RRF."""
    vec_results = vector_search(
        chroma_manager, query, top_k=top_k, where=where, min_similarity=min_similarity
    )
    bm25_results_ = bm25_search(bm25_index, query, top_k=top_k)

    logger.info(
        "Hybrid search: %d vector results, %d BM25 results",
        len(vec_results), len(bm25_results_)
    )

    fused = reciprocal_rank_fusion(
        vec_results,
        bm25_results_,
        vector_weight=vector_weight,
        bm25_weight=bm25_weight,
        relevance_threshold=relevance_threshold,
    )

    logger.info("RRF fusion: %d results above threshold %.2f", len(fused), relevance_threshold)
    return fused
