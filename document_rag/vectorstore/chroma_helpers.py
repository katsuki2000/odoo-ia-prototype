"""Helper utilities and legacy functional wrappers for ChromaDB."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
import chromadb

from config.settings import CHROMA_PATH

logger = logging.getLogger(__name__)


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


def get_chroma_client(db_path: Optional[str] = None):
    """Get a persistent ChromaDB client using configured CHROMA_PATH."""
    target_path = db_path or CHROMA_PATH
    os.makedirs(target_path, exist_ok=True)
    return chromadb.PersistentClient(path=target_path)


def get_or_create_collection(client, name: str = "miro_knowledge_base", embedding_function=None):
    """Get or create a ChromaDB collection using cosine similarity."""
    kwargs = {"name": name, "metadata": {"hnsw:space": "cosine"}}
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    return client.get_or_create_collection(**kwargs)


def add_documents(collection, documents: List[str], metadatas: List[dict], ids: List[str]):
    """Add documents to a ChromaDB collection."""
    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    logger.info("Added %d documents to collection '%s'", len(documents), collection.name)


def query_collection(collection, query_text: str, n_results: int = 5, where_filter: Optional[dict] = None):
    """Query the collection for relevant documents."""
    kwargs = {"query_texts": [query_text], "n_results": n_results}
    if where_filter:
        kwargs["where"] = where_filter
    return collection.query(**kwargs)


def reset_collection(client, name: str = "miro_knowledge_base"):
    """Delete and recreate a collection for clean re-ingestion."""
    try:
        client.delete_collection(name)
        logger.info("Deleted collection '%s'", name)
    except Exception:
        pass
    return get_or_create_collection(client, name)


def get_collection_stats(collection) -> dict:
    """Retrieve basic statistics about a collection."""
    count = collection.count()
    return {"name": collection.name, "document_count": count}
