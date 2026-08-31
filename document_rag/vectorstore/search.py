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
import os
import re
import sys
import unicodedata
from typing import Any, Optional

import numpy as np
from rank_bm25 import BM25Okapi

# Add parent directory to path for config imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import USE_RERANKER, VECTOR_SIMILARITY_FLOOR
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)


# ── Text Preprocessing ──────────────────────────────────────────────────────

# Common French + English stop words to skip for BM25 tokenization
_STOP_WORDS = frozenset([
    # French
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l",
    "et", "ou", "en", "au", "aux", "ce", "ces", "est", "sont",
    "pour", "par", "sur", "dans", "avec", "qui", "que", "ne", "pas",
    "il", "elle", "nous", "vous", "ils", "elles", "on", "se", "sa",
    "son", "ses", "leur", "leurs", "je", "tu", "mon", "ma", "mes",
    "ton", "ta", "tes", "notre", "votre", "nos", "vos",
    "à", "a", "été", "être", "avoir", "fait", "faire",
    "plus", "aussi", "très", "bien", "tout", "tous", "toute", "toutes",
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall",
    "and", "or", "but", "not", "no", "if", "then", "than",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after",
    "this", "that", "these", "those", "it", "its",
])


def _tokenize(text: str) -> list[str]:
    """
    Tokenize text for BM25 indexing.

    Normalizes unicode, lowercases, removes punctuation,
    and filters out stop words.
    """
    # Normalize unicode characters (accented chars → base + accent)
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    # Keep only alphanumeric + underscores (important for code identifiers)
    tokens = re.findall(r"[a-z0-9_]+", text)
    # Filter stop words and very short tokens
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


# ── BM25 Index ──────────────────────────────────────────────────────────────

class BM25Index:
    """
    BM25 keyword index built from ChromaDB documents.

    Maintains a parallel lexical index for keyword-based retrieval.
    """

    def __init__(self):
        self._corpus_tokens: list[list[str]] = []
        self._doc_ids: list[str] = []
        self._doc_texts: list[str] = []
        self._doc_metadatas: list[dict[str, Any]] = []
        self._bm25: BM25Okapi | None = None

    @property
    def is_built(self) -> bool:
        return self._bm25 is not None

    @property
    def size(self) -> int:
        return len(self._doc_ids)

    def build_from_chroma(
        self, chroma_manager: ChromaManager | list[ChromaManager]
    ) -> int:
        """Build BM25 index from all documents across one or more ChromaDB collections."""
        managers = chroma_manager if isinstance(chroma_manager, list) else [chroma_manager]

        all_ids: list[str] = []
        all_documents: list[str] = []
        all_metadatas: list[dict[str, Any]] = []

        for manager in managers:
            try:
                docs = manager.collection.get(include=["documents", "metadatas"])
            except Exception as e:
                logger.error(
                    "Failed to retrieve documents from collection '%s': %s",
                    getattr(manager.collection, "name", "?"), e
                )
                continue
            all_ids.extend(docs.get("ids", []))
            all_documents.extend(docs.get("documents", []))
            all_metadatas.extend(docs.get("metadatas", []))

        if not all_ids:
            logger.warning("No documents found in ChromaDB for BM25 indexing")
            return 0

        self._doc_ids = all_ids
        self._doc_texts = all_documents
        self._doc_metadatas = all_metadatas
        self._corpus_tokens = [_tokenize(doc) for doc in all_documents]

        # Build BM25 index
        self._bm25 = BM25Okapi(self._corpus_tokens)

        logger.info("BM25 index built with %d documents (%d collections)", len(all_ids), len(managers))
        return len(all_ids)

    def search(self, query: str, top_k: int = 12) -> list[dict[str, Any]]:
        """
        BM25 keyword search.

        Args:
            query: Search query text
            top_k: Number of results to return

        Returns:
            List of result dicts with id, document, metadata, score
        """
        if not self.is_built:
            logger.warning("BM25 index not built yet — returning empty results")
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            logger.warning("Query tokenized to empty — returning empty results")
            return []

        scores = self._bm25.get_scores(query_tokens)

        # Get top-k indices sorted by score (descending)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            # Skip zero-score results (no term overlap)
            if score <= 0.0:
                continue
            results.append({
                "id": self._doc_ids[idx],
                "document": self._doc_texts[idx],
                "metadata": self._doc_metadatas[idx],
                "score": score,
            })

        return results


# ── Vector Search ────────────────────────────────────────────────────────────

def vector_search(
    chroma_manager: ChromaManager | list[ChromaManager],
    query: str,
    top_k: int = 12,
    where: dict[str, Any] | None = None,
    min_similarity: float = VECTOR_SIMILARITY_FLOOR,
) -> list[dict[str, Any]]:
    """
    Vector similarity search via ChromaDB.

    Uses cosine similarity on embedded vectors (nomic-embed-text-v1.5).

    Args:
        chroma_manager: ChromaManager instance(s)
        query: Search query text
        top_k: Number of results to return
        where: Optional ChromaDB metadata filter
        min_similarity: Absolute cosine similarity floor (todo/contexte.txt
            section 292/293, Bug C root cause). ChromaDB's n_results only
            truncates a ranked list -- it never checks whether a result is
            actually relevant, so on a small corpus a query with no real
            match (e.g. a greeting) still returns near-arbitrary neighbors
            with a real-looking rank. Filtering here, upstream of RRF, is
            required because RRF fuses RANKS rather than similarity
            values, so an irrelevant result can still end up with a high
            fused score. See VECTOR_SIMILARITY_FLOOR in config/settings.py
            for how this default was calibrated.

    Returns:
        List of result dicts with id, document, metadata, similarity score,
        restricted to results at or above min_similarity.
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

    # Merge across collections, keep global top_k by similarity
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def bm25_search(
    bm25_index: BM25Index,
    query: str,
    top_k: int = 12,
) -> list[dict[str, Any]]:
    """
    BM25 keyword search.

    Args:
        bm25_index: Built BM25Index instance
        query: Search query text
        top_k: Number of results to return

    Returns:
        List of result dicts with id, document, metadata, score
    """
    return bm25_index.search(query, top_k=top_k)


# ── Reciprocal Rank Fusion (RRF) ────────────────────────────────────────────

def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
    k: int = 60,
    relevance_threshold: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion (RRF) of vector and BM25 search results.

    Combines two ranked lists using the formula:
        RRF_score(d) = w_v / (k + rank_v(d)) + w_b / (k + rank_b(d))

    Args:
        vector_results: Results from vector search (sorted by score desc)
        bm25_results: Results from BM25 search (sorted by score desc)
        vector_weight: Weight for vector search (default 0.6)
        bm25_weight: Weight for BM25 search (default 0.4)
        k: RRF constant (default 60 — standard value)
        relevance_threshold: Minimum RRF score to keep (default 0.3)

    Returns:
        Fused results sorted by combined RRF score, filtered by threshold
    """
    # Collect all unique documents by ID
    doc_map: dict[str, dict[str, Any]] = {}
    rrf_scores: dict[str, float] = {}

    # Process vector results
    for rank, result in enumerate(vector_results):
        doc_id = result["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + vector_weight / (k + rank + 1)
        if doc_id not in doc_map:
            doc_map[doc_id] = result

    # Process BM25 results
    for rank, result in enumerate(bm25_results):
        doc_id = result["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + bm25_weight / (k + rank + 1)
        if doc_id not in doc_map:
            doc_map[doc_id] = result

    # Normalize scores to [0, 1] range
    if rrf_scores:
        max_score = max(rrf_scores.values())
        if max_score > 0:
            rrf_scores = {
                doc_id: score / max_score
                for doc_id, score in rrf_scores.items()
            }

    # Build fused results, filter by threshold
    fused = []
    for doc_id, score in rrf_scores.items():
        if score >= relevance_threshold:
            result = doc_map[doc_id].copy()
            result["rrf_score"] = score
            fused.append(result)

    # Sort by RRF score descending
    fused.sort(key=lambda x: x["rrf_score"], reverse=True)

    return fused


# ── Hybrid Search ────────────────────────────────────────────────────────────

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
    """
    Hybrid search combining vector similarity and BM25 keyword matching.

    Args:
        chroma_manager: ChromaManager instance
        bm25_index: Built BM25Index instance
        query: Search query text
        top_k: Number of results from each search method
        vector_weight: Weight for vector results in RRF
        bm25_weight: Weight for BM25 results in RRF
        relevance_threshold: Minimum RRF score to keep
        min_similarity: Absolute cosine similarity floor passed through to
            vector_search() (see its docstring; todo/contexte.txt section
            292/293, Bug C root cause)
        where: Optional ChromaDB metadata filter for vector search

    Returns:
        Fused results sorted by combined RRF score
    """
    # Run both searches in parallel (sequentially here, but independent)
    vec_results = vector_search(chroma_manager, query, top_k=top_k, where=where, min_similarity=min_similarity)
    bm25_results_ = bm25_search(bm25_index, query, top_k=top_k)

    logger.info(
        "Hybrid search: %d vector results, %d BM25 results",
        len(vec_results), len(bm25_results_)
    )

    # Fuse with RRF
    fused = reciprocal_rank_fusion(
        vec_results,
        bm25_results_,
        vector_weight=vector_weight,
        bm25_weight=bm25_weight,
        relevance_threshold=relevance_threshold,
    )

    logger.info("RRF fusion: %d results above threshold %.2f", len(fused), relevance_threshold)
    return fused


# ── Cross-Encoder Re-ranking ────────────────────────────────────────────────

_cross_encoder_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_cross_encoder_instance = None  # lazy-loaded singleton, avoids reloading the model per call


def _get_cross_encoder():
    """Load and cache the local cross-encoder model (lazy singleton)."""
    global _cross_encoder_instance
    if _cross_encoder_instance is None:
        import os
        from sentence_transformers import CrossEncoder
        logger.info(f"Loading local cross-encoder model: {_cross_encoder_model_name}")
        try:
            # Force HuggingFace to load from local cache only (prevents 504 network timeouts)
            _cross_encoder_instance = CrossEncoder(_cross_encoder_model_name, local_files_only=True)
        except Exception as e:
            logger.warning(f"Failed to load CrossEncoder in offline mode, retrying online: {e}")
            _cross_encoder_instance = CrossEncoder(_cross_encoder_model_name)
    return _cross_encoder_instance


def cross_encoder_rerank(
    query: str,
    results: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Rerank results using a locally-loaded cross-encoder model.

    Runs entirely offline via sentence-transformers — no network calls,
    consistent with the project's local-first / no-cloud-dependency goal.

    Args:
        query: Original query text
        results: List of result dicts (must have 'document' key)
        top_k: Number of results to return after re-ranking

    Returns:
        Top-k results re-ranked by cross-encoder score
    """
    if not results:
        return []

    try:
        model = _get_cross_encoder()
        if model is None:
            return results[:top_k]

        # Truncate documents to keep inference fast and consistent with
        # the previous 1500-char limit used for the API payload.
        pairs = [[query, r["document"][:1500]] for r in results]

        scores = model.predict(pairs)

        for i, r in enumerate(results):
            r["cross_encoder_score"] = float(scores[i])

        results.sort(key=lambda x: x["cross_encoder_score"], reverse=True)

    except Exception as e:
        logger.error(f"Local cross-encoder reranking failed: {e}")
        logger.info("Falling back to hybrid search scores.")
        return results[:top_k]

    return results[:top_k]

# ── Full Retrieval Pipeline ─────────────────────────────────────────────────

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
    """
    Full retrieval pipeline: Vector → BM25 → RRF → Cross-Encoder → Results.

    This is the main entry point for the retrieval system.

    Args:
        query: Search query text
        top_k: Number of final results to return
        chroma_manager: ChromaManager instance (created if None)
        bm25_index: Built BM25Index instance (created and built if None)
        vector_weight: Weight for vector results in RRF
        bm25_weight: Weight for BM25 results in RRF
        relevance_threshold: Minimum RRF score to keep (RRF-level; operates
            on rank-based fused scores, not real similarity -- see Bug C,
            todo/contexte.txt section 292)
        min_similarity: Absolute cosine similarity floor applied upstream
            in vector_search(), before RRF even sees the candidates (Bug C
            root cause, todo/contexte.txt section 292/293)
        use_reranker: Whether to apply cross-encoder re-ranking
        where: Optional ChromaDB metadata filter

    Returns:
        Final ranked list of results with scores
    """
    # Initialize ChromaManager if not provided
    if chroma_manager is None:
        chroma_manager = ChromaManager()

    # Initialize and build BM25 index if not provided
    if bm25_index is None:
        bm25_index = BM25Index()
        bm25_index.build_from_chroma(chroma_manager)

    # Section 349-350 (todo/contexte.txt): the documentary RAG branch no
    # longer ingests code (Code Intelligence owns code exclusively; RAG is
    # docs-only, last-resort fallback). The former is_code_query routing
    # to a second 'odoo_code' collection is dead weight now -- that
    # collection is never populated by default, so the branch always
    # queried an empty collection. Root cause fixed at the source
    # (get_retriever() below no longer builds an odoo_code manager at
    # all), so this function now always searches the single docs
    # collection it is given, with the weights previously reserved for
    # the documentary case (vector-heavy, since prose favors semantic
    # over keyword matching).
    vector_weight = 0.7
    bm25_weight = 0.3
    chroma_manager_for_search = chroma_manager

    # Step 1+2: Hybrid search (vector + BM25 + RRF)
    # Retrieve more candidates than needed for re-ranking
    # Without reranker, we need a massive pool for RRF to work perfectly
    candidate_count = top_k * 20
    fused_results = hybrid_search(
        chroma_manager=chroma_manager_for_search,
        bm25_index=bm25_index,
        query=query,
        top_k=max(100, candidate_count),
        vector_weight=vector_weight,
        bm25_weight=bm25_weight,
        # RRF fuses ranks, not relevance -- kept permissive on purpose,
        # since real filtering now happens upstream via min_similarity
        # (Bug C root cause, todo/contexte.txt section 292/293). This
        # threshold's only remaining job is to keep enough candidates
        # around for the top_k truncation once irrelevant ones are gone.
        relevance_threshold=0.01,
        min_similarity=min_similarity,
        where=where,
    )

    if not fused_results:
        logger.warning("No results after hybrid search for query: %s", query[:100])
        return []

    # Step 3: Cross-encoder re-ranking
    if use_reranker and len(fused_results) > 1:
        final_results = cross_encoder_rerank(query, fused_results, top_k=top_k)
    else:
        final_results = fused_results[:top_k]

    logger.info(
        "Retrieval complete: %d results for query '%s'",
        len(final_results), query[:80]
    )

    # Section 289/290 (todo/contexte.txt), point (2) -- Bug C instrumentation.
    # Structured trace of the FINAL results actually handed to generate():
    # question, candidate pool size before/after rerank, and per-result
    # rank/id/score/score_type/source/type. Goal: confirm or infirm
    # empirically whether low-signal questions (e.g. "Bonjour") receive
    # irrelevant chunks (e.g. frontend source code cited for a greeting)
    # because of an overly permissive retrieval pipeline, rather than
    # deducing it from code reading alone. Mirrors the same
    # json.dumps({"event": ...}) structured-log convention already used by
    # core/graph.py::query_graph() for latency metrics.
    # Bug A (todo/contexte.txt section 289/292) -- top1 chunk excerpt, bounded
    # to avoid log bloat. Lets the exact text handed to generate() be
    # inspected directly instead of deducing whether literal HTML entities
    # (e.g. &#039;, <br/>) originate from the indexed chunk itself, the LLM,
    # or a later rendering step.
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
        # Never let tracing/logging failures break the retrieval pipeline itself.
        logger.warning("retrieval_trace logging failed (non-blocking): %s", e)

    return final_results


# ── Convenience: Singleton manager for reuse ─────────────────────────────────

_shared_chroma: ChromaManager | None = None
_shared_bm25: BM25Index | None = None


def get_retriever() -> tuple[ChromaManager, BM25Index]:
    """
    Get or create the shared ChromaManager and BM25Index instances.

    Section 349-350 (todo/contexte.txt): documentary RAG now searches only
    the 'odoo_docs' collection -- Code Intelligence owns code exclusively,
    RAG is a docs-only, last-resort fallback. No 'odoo_code' manager is
    built here anymore: it was never populated by default since that
    decision, so building it unconditionally on every startup was dead
    weight (an extra ChromaDB connection plus an always-empty slice of
    every BM25 index rebuild).

    Returns:
        Tuple of (ChromaManager, BM25Index) ready for use
    """
    global _shared_chroma, _shared_bm25

    if _shared_chroma is None:
        _shared_chroma = ChromaManager(collection_name="odoo_docs")

    if _shared_bm25 is None or not _shared_bm25.is_built:
        _shared_bm25 = BM25Index()
        _shared_bm25.build_from_chroma(_shared_chroma)

    return _shared_chroma, _shared_bm25


def quick_retrieve(query: str, top_k: int = 5, **kwargs) -> list[dict[str, Any]]:
    """
    Quick retrieval using shared instances.

    Args:
        query: Search query
        top_k: Number of results
        **kwargs: Additional arguments passed to retrieve()

    Returns:
        List of results
    """
    chroma, bm25 = get_retriever()
    return retrieve(
        query=query,
        top_k=top_k,
        chroma_manager=chroma,
        bm25_index=bm25,
        **kwargs,
    )
