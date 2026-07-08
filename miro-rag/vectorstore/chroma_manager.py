"""
vectorstore/chroma_manager.py

Manages the ChromaDB vector store:
- Initializes a persistent ChromaDB client
- Creates/gets collections for different data types
- Provides add/query methods with metadata filtering
"""

import os
import sys
import chromadb

# Add parent directory to path for config imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import CHROMA_PATH


def get_chroma_client():
    """Get a persistent ChromaDB client."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vectorstore", "chroma_db")
    os.makedirs(db_path, exist_ok=True)
    client = chromadb.PersistentClient(path=db_path)
    return client


def get_or_create_collection(client, name="miro_knowledge_base"):
    """Get or create a ChromaDB collection using cosine similarity."""
    collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def add_documents(collection, documents, metadatas, ids):
    """
    Add documents to a ChromaDB collection.

    Args:
        collection: ChromaDB collection object
        documents: List of text chunks
        metadatas: List of metadata dictionaries (source, type, client, etc.)
        ids: List of unique string IDs
    """
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids,
    )
    print(f"Added {len(documents)} documents to collection '{collection.name}'")


def query_collection(collection, query_text, n_results=5, where_filter=None):
    """
    Query the collection for relevant documents.

    Args:
        collection: ChromaDB collection object
        query_text: The query string
        n_results: Number of results to return
        where_filter: Optional metadata filter dictionary

    Returns:
        Dictionary containing 'documents', 'metadatas', 'distances', and 'ids'
    """
    kwargs = {
        "query_texts": [query_text],
        "n_results": n_results,
    }
    if where_filter:
        kwargs["where"] = where_filter

    return collection.query(**kwargs)


def reset_collection(client, name="miro_knowledge_base"):
    """Delete and recreate a collection for clean re-ingestion."""
    try:
        client.delete_collection(name)
        print(f"Deleted collection '{name}'")
    except Exception:
        pass
    return get_or_create_collection(client, name)


def get_collection_stats(collection):
    """Retrieve basic statistics about a collection."""
    count = collection.count()
    return {"name": collection.name, "document_count": count}


if __name__ == "__main__":
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    stats = get_collection_stats(collection)
    print(f"Collection '{stats['name']}': {stats['document_count']} documents")
