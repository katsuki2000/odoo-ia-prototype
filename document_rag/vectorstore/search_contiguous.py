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


def _manager_for_chunk(chroma_manager: Any, source: str, chunk_id: str) -> Any:
    managers = chroma_manager if isinstance(chroma_manager, list) else [chroma_manager]
    for manager in managers:
        if not manager or not hasattr(manager, "collection"):
            continue
        try:
            seed = manager.collection.get(ids=[chunk_id], include=["metadatas"])
        except Exception:
            continue
        if any(
            found_id == chunk_id and metadata and metadata.get("source") == source
            for found_id, metadata in zip(seed.get("ids", []), seed.get("metadatas", []))
        ):
            return manager
    return None


def _source_key(item: Mapping[str, Any], chroma_manager: Any) -> tuple[Any, int | None] | None:
    source = (item.get("metadata") or {}).get("source")
    if not source:
        return None
    manager = (
        _manager_for_chunk(chroma_manager, source, item.get("id"))
        if isinstance(chroma_manager, list) and item.get("id")
        else chroma_manager
    )
    return source, id(manager) if manager is not None else None


def fetch_source_chunks(chroma_manager: Any, source: str, chunk_id: str | None = None) -> dict[int, dict[str, Any]]:
    """Fetch and index all chunks of a source by chunk_index."""
    managers = chroma_manager if isinstance(chroma_manager, list) else [chroma_manager]
    if chunk_id and isinstance(chroma_manager, list):
        manager = _manager_for_chunk(chroma_manager, source, chunk_id)
        managers = [manager] if manager is not None else []
    by_index = {}
    for manager in managers:
        if not manager or not hasattr(manager, "collection"):
            continue
        try:
            results = manager.collection.get(where={"source": source})
            for found_id, document, metadata in zip(
                results.get("ids", []), results.get("documents", []), results.get("metadatas", [])
            ):
                if metadata and "chunk_index" in metadata:
                    by_index.setdefault(metadata["chunk_index"], {
                        "id": found_id,
                        "document": document,
                        "metadata": metadata,
                    })
        except Exception as error:
            logger.warning("Failed to fetch contiguous chunks for %s: %s", source, error)
    return by_index


def expand_dominant_documents(
    results: Sequence[Mapping[str, Any]],
    chroma_manager: Any = None,
    min_chunks: int = RAG_DOCUMENT_EXPANSION_MIN_CHUNKS,
    max_chunks: int = RAG_DOCUMENT_EXPANSION_MAX_CHUNKS,
) -> list[dict[str, Any]]:
    """Expand a source when several retrieved chunks show that it dominates the answer."""
    if not results or chroma_manager is None:
        return [dict(item) for item in results]

    keys = [_source_key(item, chroma_manager) for item in results]
    counts = Counter(key for key in keys if key)
    whole_documents = {}
    for key, count in counts.items():
        if count < min_chunks:
            continue
        seed = next(item for item, item_key in zip(results, keys) if item_key == key)
        available = fetch_source_chunks(chroma_manager, key[0], chunk_id=seed.get("id"))
        if available and len(available) <= max_chunks:
            whole_documents[key] = available

    expanded, done = [], set()
    for item, key in zip(results, keys):
        if key not in whole_documents:
            expanded.append(dict(item))
        elif key not in done:
            done.add(key)
            retrieved = {
                (chunk.get("metadata") or {}).get("chunk_index"): chunk
                for chunk, chunk_key in zip(results, keys) if chunk_key == key
            }
            for index in sorted(whole_documents[key]):
                expanded.append(dict(retrieved.get(index) or whole_documents[key][index]))
    return expanded


def expand_contiguous_chunks(
    results: Sequence[Mapping[str, Any]],
    chroma_manager: Any = None,
) -> list[dict[str, Any]]:
    """Add adjacent chunks for retrieved fragments containing lists or tables."""
    if not results or chroma_manager is None:
        return [dict(item) for item in results]
    if not any(contains_list_or_table(item.get("document", "")) for item in results):
        return [dict(item) for item in results]

    keys = [_source_key(item, chroma_manager) for item in results]
    expanded_by_source = {}
    known_keys = set()
    source_cache = {}

    for item, source_key in zip(results, keys):
        metadata = item.get("metadata") or {}
        index = metadata.get("chunk_index")
        if source_key and index is not None:
            known_keys.add((source_key, index))
            expanded_by_source.setdefault(source_key, {})[index] = dict(item)

    for item, source_key in zip(results, keys):
        if not source_key or not contains_list_or_table(item.get("document", "")):
            continue
        metadata = item.get("metadata") or {}
        index = metadata.get("chunk_index")
        total = metadata.get("total_chunks")
        if index is None:
            continue
        if source_key not in source_cache:
            source_cache[source_key] = fetch_source_chunks(
                chroma_manager, source_key[0], chunk_id=item.get("id")
            )
        available = source_cache[source_key]
        for adjacent_index in (index - 1, index + 1):
            if 0 <= adjacent_index and (total is None or adjacent_index < total):
                key = (source_key, adjacent_index)
                if key not in known_keys and adjacent_index in available:
                    chunk = dict(available[adjacent_index])
                    chunk["is_contiguous_expansion"] = True
                    expanded_by_source.setdefault(source_key, {})[adjacent_index] = chunk
                    known_keys.add(key)

    final_results, seen_sources = [], set()
    for item, source_key in zip(results, keys):
        if source_key in expanded_by_source:
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                final_results.extend(
                    expanded_by_source[source_key][index]
                    for index in sorted(expanded_by_source[source_key])
                )
        else:
            final_results.append(dict(item))
    return final_results
