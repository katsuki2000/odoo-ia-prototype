#!/usr/bin/env python3
"""
tools/ingest_to_vectorstore.py

Master ingestion script:
1. Loads all documents (wiki, PDFs, tickets, sales) via pdf_loader
2. Resets the ChromaDB collection
3. Adds all chunked documents with metadata in batches
4. Verifies with a test query
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.pdf_loader import load_all
from vectorstore.chroma_manager import (
    get_chroma_client, reset_collection, add_documents, get_collection_stats
)


def main():
    print("RAG Vectorstore Ingestion Pipeline")
    print("=" * 55)

    documents, metadatas, ids = load_all()

    if not documents:
        print("Error: No documents found. Please check the fake_data directory.")
        sys.exit(1)

    print("\nInitializing ChromaDB...")
    client = get_chroma_client()
    collection = reset_collection(client, "miro_knowledge_base")

    print("\nAdding documents to vectorstore...")
    batch_size = 50
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i:i + batch_size]
        batch_meta = metadatas[i:i + batch_size]
        batch_ids = ids[i:i + batch_size]
        add_documents(collection, batch_docs, batch_meta, batch_ids)

    stats = get_collection_stats(collection)
    print(f"\nCollection Stats:")
    print(f"  - Name: {stats['name']}")
    print(f"  - Total documents: {stats['document_count']}")

    type_counts = {}
    for m in metadatas:
        t = m['type']
        type_counts[t] = type_counts.get(t, 0) + 1
    print("  - Breakdown:")
    for t, c in sorted(type_counts.items()):
        print(f"    * {t}: {c} chunks")

    print("\nRunning verification query: 'Comment résoudre une facture bloquée ?'")
    results = collection.query(
        query_texts=["Comment résoudre une facture bloquée ?"],
        n_results=3,
    )
    print(f"Found {len(results['documents'][0])} results:")
    for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
        print(f"  [{i+1}] {meta.get('type', 'unknown')} | {meta.get('title', meta.get('source', 'unknown'))}")
        print(f"      -> {doc[:120]}...")

    print("\n" + "=" * 55)
    print("Vectorstore ingestion completed successfully. Ready for RAG queries.")


if __name__ == "__main__":
    main()
