"""Hybrid document retrieval with current Drive chunk availability checks."""

from __future__ import annotations

import json
import logging
from typing import Any
from config.settings import RAG_BM25_WEIGHT, RAG_RELEVANCE_THRESHOLD, RAG_VECTOR_WEIGHT, VECTOR_SIMILARITY_FLOOR
from document_rag.vectorstore.bm25_index import _STOP_WORDS, _tokenize, BM25Index, bm25_search
from document_rag.vectorstore.chroma_manager import ChromaManager
from document_rag.vectorstore.search_hybrid import hybrid_search, vector_search
from document_rag.vectorstore.search_ranking import reciprocal_rank_fusion
from document_rag.vectorstore.search_contiguous import expand_contiguous_chunks
from document_rag.vectorstore.drive_guard import filter_current_drive_chunks

logger = logging.getLogger(__name__)


def retrieve(query: str, top_k: int = 5, chroma_manager: ChromaManager | list[ChromaManager] | None = None,
             bm25_index: BM25Index | None = None, vector_weight: float = RAG_VECTOR_WEIGHT,
             bm25_weight: float = RAG_BM25_WEIGHT, relevance_threshold: float = RAG_RELEVANCE_THRESHOLD, min_similarity: float = VECTOR_SIMILARITY_FLOOR,
             where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if chroma_manager is None:
        chroma_manager = ChromaManager()
    if bm25_index is None:
        bm25_index = BM25Index()
        bm25_index.build_from_chroma(chroma_manager)
    candidate_count = top_k * 20
    fused_results = hybrid_search(chroma_manager=chroma_manager, bm25_index=bm25_index, query=query,
                                   top_k=max(100, candidate_count), vector_weight=vector_weight, bm25_weight=bm25_weight,
                                   relevance_threshold=relevance_threshold, min_similarity=min_similarity, where=where)
    fused_results = filter_current_drive_chunks(fused_results, chroma_manager)
    if not fused_results:
        logger.warning('No results after hybrid search for query: %s', query[:100])
        return []
    final_results = expand_contiguous_chunks(fused_results[:top_k], chroma_manager=chroma_manager)
    final_results = filter_current_drive_chunks(final_results, chroma_manager)
    logger.info("Retrieval complete: %d results for query '%s'", len(final_results), query[:80])
    top1_excerpt = None
    if final_results:
        top1 = final_results[0]
        top1_excerpt = {'id': top1.get('id'), 'source': (top1.get('metadata') or {}).get('source', 'unknown'),
                        'type': (top1.get('metadata') or {}).get('type', 'unknown'),
                        'score': top1.get('rrf_score', top1.get('score')),
                        'text_excerpt': (top1.get('document') or '')[:400]}
    try:
        logger.info(json.dumps({'event': 'retrieval_trace', 'question': query, 'vector_weight': vector_weight,
                                'bm25_weight': bm25_weight, 'fused_count': len(fused_results),
                                'final_count': len(final_results),
                                'top1': top1_excerpt, 'results': [
                                    {'rank': index + 1, 'id': item.get('id'),
                                     'score': item.get('rrf_score', item.get('score')),
                                     'score_type': 'rrf' if 'rrf_score' in item else 'raw',
                                     'source': (item.get('metadata') or {}).get('source', 'unknown'),
                                     'type': (item.get('metadata') or {}).get('type', 'unknown')}
                                    for index, item in enumerate(final_results)]}))
    except Exception as error:
        logger.warning('retrieval_trace logging failed (non-blocking): %s', error)
    return final_results


_shared_chroma: ChromaManager | None = None
_shared_bm25: BM25Index | None = None


def get_retriever() -> tuple[ChromaManager, BM25Index]:
    global _shared_chroma, _shared_bm25
    if _shared_chroma is None:
        _shared_chroma = ChromaManager()
    if _shared_bm25 is None or not _shared_bm25.is_built or not _shared_bm25.matches(_shared_chroma):
        _shared_bm25 = BM25Index()
        _shared_bm25.build_from_chroma(_shared_chroma)
    return _shared_chroma, _shared_bm25


def quick_retrieve(query: str, top_k: int = 5, **kwargs) -> list[dict[str, Any]]:
    chroma, bm25 = get_retriever()
    return retrieve(query=query, top_k=top_k, chroma_manager=chroma, bm25_index=bm25, **kwargs)


__all__ = ['BM25Index', '_STOP_WORDS', '_tokenize', 'bm25_search', 'vector_search', 'reciprocal_rank_fusion',
           'hybrid_search', 'retrieve', 'get_retriever', 'quick_retrieve']
