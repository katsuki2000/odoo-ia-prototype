"""Helper utilities for formatting and cleaning ChromaDB query results and metadata."""

import json
from typing import Any, Dict


def clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Clean and validate metadata for storage in ChromaDB."""
    cleaned = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, (dict, list)):
            cleaned[key] = json.dumps(value)
        else:
            cleaned[key] = str(value)
    return cleaned


def format_query_results(raw_results: Dict[str, Any]) -> Dict[str, Any]:
    """Format raw ChromaDB query results into a structured dictionary."""
    formatted = {"results": [], "count": 0}
    if not raw_results or not raw_results.get("ids"):
        return formatted

    ids = raw_results["ids"][0] if raw_results["ids"] else []
    documents = raw_results["documents"][0] if raw_results["documents"] else []
    distances = raw_results["distances"][0] if raw_results["distances"] else []
    metadatas = raw_results["metadatas"][0] if raw_results["metadatas"] else []

    for i in range(len(ids)):
        dist = float(distances[i]) if i < len(distances) else 0.0
        result = {
            "id": ids[i],
            "document": documents[i] if i < len(documents) else "",
            "distance": dist,
            "similarity": 1.0 - dist,
            "metadata": metadatas[i] if i < len(metadatas) else {},
        }
        formatted["results"].append(result)

    formatted["count"] = len(ids)
    return formatted
