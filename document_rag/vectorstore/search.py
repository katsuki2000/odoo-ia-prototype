"""
Hybrid Search Module — Vector + BM25 + RRF + Cross-Encoder Re-ranking.

Implements the full retrieval pipeline for the MIRO AI RAG system:
1. Vector search via ChromaDB (cosine similarity)
2. BM25 keyword search (lexical matching)
3. Reciprocal Rank Fusion (RRF) to merge both result sets
4. Cross-encoder re-ranking for final precision

Usage:
    from document_rag.vectorstore.search import retrieve
    results = retrieve("Comment créer une facture ?", top_k=5)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import USE_RERANKER, VECTOR_SIMILARITY_FLOOR
from document_rag.vectorstore.bm25_index import (
    _STOP_WORDS,
    _tokenize,
    BM25Index,
    bm25_search,
)
from document_rag.vectorstore.chroma_manager import ChromaManager
from document_rag.vectorstore.search_hybrid import hybrid_search, vector_search
from document_rag.vectorstore.search_ranking import (
    _cross_encoder_model_name,
    _get_cross_encoder,
    cross_encoder_rerank,
    reciprocal_rank_fusion,
)
from document_rag.vectorstore.search_contiguous import expand_contiguous_chunks

logger = logging.getLogger(__name__)


def retrieve(
    query: str,
    top_k: int = 5,
    chroma_manager: ChromaManager | list[ChromaManager] | None = None,
    bm25_index: BM25Index | None = None,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
    relevance_threshold: float = 0.3,
    min_similarity: float = VECTOR_SIMILARITY_FLOOR,
    use_reranker: bool = USE_RERANKER,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Full retrieval pipeline: Vector -> BM25 -> RRF -> Cross-Encoder -> Results."""
    if chroma_manager is None:
        chroma_manager = ChromaManager()

    if bm25_index is None:
        bm25_index = BM25Index()
        bm25_index.build_from_chroma(chroma_manager)

    vector_weight = 0.7
    bm25_weight = 0.3
    candidate_count = top_k * 20

    fused_results = hybrid_search(
        chroma_manager=chroma_manager,
        bm25_index=bm25_index,
        query=query,
        top_k=max(100, candidate_count),
        vector_weight=vector_weight,
        bm25_weight=bm25_weight,
        relevance_threshold=0.01,
        min_similarity=min_similarity,
        where=where,
    )

    if not fused_results:
        logger.warning("No results after hybrid search for query: %s", query[:100])
        return []

    if use_reranker and len(fused_results) > 1:
        final_results = cross_encoder_rerank(query, fused_results, top_k=top_k)
    else:
        final_results = fused_results[:top_k]

    final_results = expand_contiguous_chunks(final_results, chroma_manager=chroma_manager)

    logger.info("Retrieval complete: %d results for query '%s'", len(final_results), query[:80])


    top1_excerpt = None
    if final_results:
        top1 = final_results[0]
        top1_excerpt = {
            "id": top1.get("id"),
            "source": (top1.get("metadata") or {}).get("source", "unknown"),
            "type": (top1.get("metadata") or {}).get("type", "unknown"),
            "score": top1.get("cross_encoder_score", top1.get("rrf_score", top1.get("score"))),
            "text_excerpt": (top1.get("document") or "")[:400],
        }

    try:
        logger.info(json.dumps({
            "event": "retrieval_trace",
            "question": query,
            "vector_weight": vector_weight,
            "bm25_weight": bm25_weight,
            "candidate_count_before_rerank": len(fused_results),
            "final_count": len(final_results),
            "reranker_used": bool(use_reranker and len(fused_results) > 1),
            "top1": top1_excerpt,
            "results": [
                {
                    "rank": i + 1,
                    "id": r.get("id"),
                    "score": r.get("cross_encoder_score", r.get("rrf_score", r.get("score"))),
                    "score_type": (
                        "cross_encoder" if "cross_encoder_score" in r
                        else "rrf" if "rrf_score" in r
                        else "raw"
                    ),
                    "source": (r.get("metadata") or {}).get("source", "unknown"),
                    "type": (r.get("metadata") or {}).get("type", "unknown"),
                }
                for i, r in enumerate(final_results)
            ],
        }))
    except Exception as e:
        logger.warning("retrieval_trace logging failed (non-blocking): %s", e)

    return final_results


_shared_chroma: ChromaManager | None = None
_shared_bm25: BM25Index | None = None


def get_retriever() -> tuple[ChromaManager, BM25Index]:
    """Get or create the shared ChromaManager and BM25Index instances."""
    global _shared_chroma, _shared_bm25

    if _shared_chroma is None:
        _shared_chroma = ChromaManager()

    if _shared_bm25 is None or not _shared_bm25.is_built:
        _shared_bm25 = BM25Index()
        _shared_bm25.build_from_chroma(_shared_chroma)

    return _shared_chroma, _shared_bm25


def quick_retrieve(query: str, top_k: int = 5, **kwargs) -> list[dict[str, Any]]:
    """Quick retrieval using shared instances."""
    chroma, bm25 = get_retriever()
    return retrieve(
        query=query,
        top_k=top_k,
        chroma_manager=chroma,
        bm25_index=bm25,
        **kwargs,
    )


__all__ = [
    "BM25Index",
    "_STOP_WORDS",
    "_tokenize",
    "bm25_search",
    "vector_search",
    "reciprocal_rank_fusion",
    "cross_encoder_rerank",
    "_get_cross_encoder",
    "_cross_encoder_model_name",
    "hybrid_search",
    "retrieve",
    "get_retriever",
    "quick_retrieve",
]
