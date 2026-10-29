"""
document_rag/vectorstore/search_contiguous.py

Expand retrieved document chunks with contiguous fragments when they contain lists or tables.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Mapping, Sequence

from config.settings import RAG_DOCUMENT_EXPANSION_MAX_CHUNKS, RAG_DOCUMENT_EXPANSION_MIN_CHUNKS

logger = logging.getLogger(__name__)

LIST_OR_TABLE_RE = re.compile(
    r"(?:^[ \t]*[-*•]\s+\S|^\s*\d+[.)]\s+\S|^\s*\|.+\|)",
    re.MULTILINE,
)


def contains_list_or_table(text: str) -> bool:
    """Return True if text contains bullet lists, numbered items, or markdown tables."""
    return bool(LIST_OR_TABLE_RE.search(text))


def fetch_source_chunks(chroma_manager: Any, source: str) -> dict[int, dict[str, Any]]:
    """Fetch and index all chunks of a source by chunk_index."""
    if not chroma_manager or not hasattr(chroma_manager, "collection"):
        return {}
    try:
        results = chroma_manager.collection.get(where={"source": source})
        if not results or not results.get("ids"):
            return {}
        by_index = {}
        for cid, doc, meta in zip(results["ids"], results["documents"], results["metadatas"]):
            if meta and "chunk_index" in meta:
                by_index[meta["chunk_index"]] = {
                    "id": cid,
                    "document": doc,
                    "metadata": meta,
                }
        return by_index
    except Exception as e:
        logger.warning("Failed to fetch contiguous chunks for %s: %s", source, e)
        return {}


def expand_dominant_documents(
    results: Sequence[Mapping[str, Any]],
    chroma_manager: Any = None,
    min_chunks: int = RAG_DOCUMENT_EXPANSION_MIN_CHUNKS,
    max_chunks: int = RAG_DOCUMENT_EXPANSION_MAX_CHUNKS,
) -> list[dict[str, Any]]:
    """
    Read in full a document that dominates the results.

    A question asking for an exhaustive list (rules, steps) is answered by many chunks of one document, and the
    ranking keeps only the best-scored ones. A document with at least min_chunks chunks among the results is the
    source of the answer: its chunks are returned in document order, where its first chunk was, and the retrieved
    ones keep their scores. A document of more than max_chunks chunks, or one that cannot be read, is left as is.
    """
    if not results or chroma_manager is None:
        return [dict(item) for item in results]

    def source_of(item: Mapping[str, Any]) -> Any:
        return (item.get("metadata") or {}).get("source")

    counts = Counter(source_of(item) for item in results)
    whole_documents = {}
    for source, count in counts.items():
        if source and count >= min_chunks:
            available = fetch_source_chunks(chroma_manager, source)
            if available and len(available) <= max_chunks:
                whole_documents[source] = available

    expanded, done = [], set()
    for item in results:
        source = source_of(item)
        if source not in whole_documents:
            expanded.append(dict(item))
        elif source not in done:
            done.add(source)
            retrieved = {(chunk.get("metadata") or {}).get("chunk_index"): chunk for chunk in results if source_of(chunk) == source}
            for index in sorted(whole_documents[source]):
                expanded.append(dict(retrieved.get(index) or whole_documents[source][index]))
    return expanded


def expand_contiguous_chunks(
    results: Sequence[Mapping[str, Any]],
    chroma_manager: Any = None,
) -> list[dict[str, Any]]:
    """
    Ensure complete list and table retrieval by pulling adjacent chunks
    (chunk_index - 1, chunk_index + 1) for any chunk containing lists or tables.
    """
    if not results or chroma_manager is None:
        return [dict(item) for item in results]

    has_any_list = any(contains_list_or_table(item.get("document", "")) for item in results)
    if not has_any_list:
        return [dict(item) for item in results]

    expanded_by_source: dict[str, dict[int, dict[str, Any]]] = {}
    known_keys = set()
    source_cache: dict[str, dict[int, dict[str, Any]]] = {}

    for item in results:
        meta = item.get("metadata") or {}
        source = meta.get("source")
        idx = meta.get("chunk_index")
        if source and idx is not None:
            known_keys.add((source, idx))
            expanded_by_source.setdefault(source, {})[idx] = dict(item)

    for item in results:
        doc = item.get("document", "")
        if not contains_list_or_table(doc):
            continue

        meta = item.get("metadata") or {}
        source = meta.get("source")
        idx = meta.get("chunk_index")
        total = meta.get("total_chunks")
        if not source or idx is None:
            continue

        if source not in source_cache:
            source_cache[source] = fetch_source_chunks(chroma_manager, source)
        available = source_cache[source]

        for adjacent_idx in (idx - 1, idx + 1):
            if 0 <= adjacent_idx and (total is None or adjacent_idx < total):
                if (source, adjacent_idx) not in known_keys and adjacent_idx in available:
                    adj_chunk = dict(available[adjacent_idx])
                    adj_chunk["is_contiguous_expansion"] = True
                    expanded_by_source.setdefault(source, {})[adjacent_idx] = adj_chunk
                    known_keys.add((source, adjacent_idx))

    final_results = []
    seen_sources = set()
    for item in results:
        src = (item.get("metadata") or {}).get("source")
        if src and src in expanded_by_source:
            if src not in seen_sources:
                seen_sources.add(src)
                for idx in sorted(expanded_by_source[src].keys()):
                    final_results.append(expanded_by_source[src][idx])
        else:
            final_results.append(dict(item))

    return final_results
