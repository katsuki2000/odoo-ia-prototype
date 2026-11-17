"""
document_rag/retrieval/search_contiguous.py

Expand retrieved document chunks with contiguous fragments when they contain lists or tables.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Iterator, Mapping, Sequence

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
    ones keep their scores. The chunks of the other documents are dropped: the top-k always fills up, so they are
    the least relevant ones, not evidence. A document of more than max_chunks chunks, or one that cannot be read,
    is left as is.
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
            if not whole_documents:
                expanded.append(dict(item))
        elif source not in done:
            done.add(source)
            retrieved = {(chunk.get("metadata") or {}).get("chunk_index"): chunk for chunk in results if source_of(chunk) == source}
            for index in sorted(whole_documents[source]):
                expanded.append(dict(retrieved.get(index) or whole_documents[source][index]))
    return expanded


def _adjacent_indexes(meta: Mapping[str, Any], available: Mapping[int, Mapping[str, Any]]) -> Iterator[int]:
    """
    Indexes of the chunks to add around a chunk holding a list or a table: its two neighbours, and, for a
    table, the following chunks of the same table (same section, table rows) in each direction.
    """
    in_table = bool(meta.get("has_table"))
    for step in (-1, 1):
        for distance in range(1, RAG_DOCUMENT_EXPANSION_MAX_CHUNKS + 1):
            index = meta["chunk_index"] + step * distance
            if index not in available:
                break
            yield index
            neighbour = available[index]["metadata"]
            if not (in_table and neighbour.get("has_table") and neighbour.get("section") == meta.get("section")):
                break


def expand_contiguous_chunks(
    results: Sequence[Mapping[str, Any]],
    chroma_manager: Any = None,
) -> list[dict[str, Any]]:
    """
    Ensure complete list and table retrieval: a chunk containing a list or a table brings its two neighbours,
    and a table is followed to its end, so that a table found by one of its chunks is returned whole.
    """
    if not results or chroma_manager is None:
        return [dict(item) for item in results]

    chunks_by_source: dict[str, dict[int, dict[str, Any]]] = {}
    for item in results:
        meta = item.get("metadata") or {}
        if meta.get("source") and meta.get("chunk_index") is not None:
            chunks_by_source.setdefault(meta["source"], {})[meta["chunk_index"]] = dict(item)

    source_cache: dict[str, dict[int, dict[str, Any]]] = {}
    for item in results:
        meta = item.get("metadata") or {}
        source = meta.get("source")
        if not source or meta.get("chunk_index") is None or not contains_list_or_table(item.get("document", "")):
            continue
        if source not in source_cache:
            source_cache[source] = fetch_source_chunks(chroma_manager, source)
        available = source_cache[source]
        for index in _adjacent_indexes(meta, available):
            chunks_by_source[source].setdefault(index, {**available[index], "is_contiguous_expansion": True})

    final_results = []
    seen_sources = set()
    for item in results:
        source = (item.get("metadata") or {}).get("source")
        if source not in chunks_by_source:
            final_results.append(dict(item))
        elif source not in seen_sources:
            seen_sources.add(source)
            final_results.extend(chunks_by_source[source][index] for index in sorted(chunks_by_source[source]))
    return final_results
