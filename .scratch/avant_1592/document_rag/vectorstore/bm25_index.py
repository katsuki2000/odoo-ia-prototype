"""
BM25 Keyword Indexing and Tokenization for Hybrid Search.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

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
    """Tokenize text for BM25 indexing, normalizing unicode and filtering stop words."""
    text = unicodedata.normalize("NFKD", text).lower()
    tokens = re.findall(r"[a-z0-9_]+", text)
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


class BM25Index:
    """BM25 keyword index built from ChromaDB documents."""

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
        self._bm25 = BM25Okapi(self._corpus_tokens)

        logger.info("BM25 index built with %d documents (%d collections)", len(all_ids), len(managers))
        return len(all_ids)

    def search(self, query: str, top_k: int = 12) -> list[dict[str, Any]]:
        """Perform BM25 keyword search returning top_k results."""
        if not self.is_built:
            logger.warning("BM25 index not built yet — returning empty results")
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            logger.warning("Query tokenized to empty — returning empty results")
            return []

        scores = self._bm25.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score <= 0.0:
                continue
            results.append({
                "id": self._doc_ids[idx],
                "document": self._doc_texts[idx],
                "metadata": self._doc_metadatas[idx],
                "score": score,
            })

        return results


def bm25_search(
    bm25_index: BM25Index,
    query: str,
    top_k: int = 12,
) -> list[dict[str, Any]]:
    """Execute BM25 keyword search using provided index."""
    return bm25_index.search(query, top_k=top_k)
