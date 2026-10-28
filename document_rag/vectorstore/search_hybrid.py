"""Vector and lexical search with live Drive availability checks."""

from __future__ import annotations

import logging
from typing import Any
from config.settings import RAG_BM25_WEIGHT, RAG_RELEVANCE_THRESHOLD, RAG_VECTOR_WEIGHT, VECTOR_SIMILARITY_FLOOR
from document_rag.vectorstore.bm25_index import BM25Index, bm25_search
from document_rag.vectorstore.chroma_manager import ChromaManager
from document_rag.vectorstore.search_ranking import reciprocal_rank_fusion
from document_rag.vectorstore.drive_guard import filter_current_drive_chunks

logger = logging.getLogger(__name__)


def vector_search(chroma_manager: ChromaManager | list[ChromaManager], query: str, top_k: int = 12,
                  where: dict[str, Any] | None = None, min_similarity: float = VECTOR_SIMILARITY_FLOOR) -> list[dict[str, Any]]:
    managers = chroma_manager if isinstance(chroma_manager, list) else [chroma_manager]
    results = []
    for manager in managers:
        raw = manager.query(query_text=query, top_k=top_k, where=where)
        for item in raw.get('results', []):
            if item['similarity'] < min_similarity:
                continue
            results.append({'id': item['id'], 'document': item['document'], 'metadata': item['metadata'], 'score': item['similarity']})
    results = filter_current_drive_chunks(results, managers)
    results.sort(key=lambda item: item['score'], reverse=True)
    return results[:top_k]


def hybrid_search(chroma_manager: ChromaManager | list[ChromaManager], bm25_index: BM25Index, query: str,
                  top_k: int = 12, vector_weight: float = RAG_VECTOR_WEIGHT, bm25_weight: float = RAG_BM25_WEIGHT,
                  relevance_threshold: float = RAG_RELEVANCE_THRESHOLD, min_similarity: float = VECTOR_SIMILARITY_FLOOR,
                  where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    vec_results = vector_search(chroma_manager, query, top_k=top_k, where=where, min_similarity=min_similarity)
    bm25_results_ = filter_current_drive_chunks(bm25_search(bm25_index, query, top_k=top_k), chroma_manager)
    logger.info('Hybrid search: %d vector results, %d BM25 results', len(vec_results), len(bm25_results_))
    fused = reciprocal_rank_fusion(vec_results, bm25_results_, vector_weight=vector_weight, bm25_weight=bm25_weight,
                                   relevance_threshold=relevance_threshold)
    logger.info('RRF fusion: %d results above threshold %.2f', len(fused), relevance_threshold)
    return fused
