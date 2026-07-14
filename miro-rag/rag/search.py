"""
Search script for querying dual ChromaDB collections (odoo_docs and odoo_code).
Merges results by score since they use the same embedding space.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vectorstore.chroma_manager import ChromaManager

def search_all(query: str, top_k: int = 5, db_path: str = "vectorstore/chroma_db") -> list[dict[str, Any]]:
    docs_manager = ChromaManager(db_path=db_path, collection_name="odoo_docs")
    code_manager = ChromaManager(db_path=db_path, collection_name="odoo_code")
    
    # Query both collections
    docs_results = docs_manager.query(query, top_k=top_k)
    code_results = code_manager.query(query, top_k=top_k)
    
    # Combine results
    all_results = docs_results.get("results", []) + code_results.get("results", [])
    
    # Sort by similarity (highest first)
    all_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    
    # Return top_k overall
    return all_results[:top_k]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search Odoo RAG")
    parser.add_argument("query", type=str, help="Search query")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to return")
    parser.add_argument("--db-path", type=str, default="miro-rag/vectorstore/chroma_db", help="Path to ChromaDB")
    
    args = parser.parse_args()
    
    print(f"\nSearching for: '{args.query}'\n" + "="*50)
    
    results = search_all(args.query, top_k=args.top_k, db_path=args.db_path)
    
    for i, res in enumerate(results, 1):
        metadata = res.get('metadata', {})
        source = metadata.get('source', 'Unknown')
        doc_type = metadata.get('type', 'Unknown')
        score = res.get('similarity', 0)
        
        print(f"\n{i}. [{doc_type}] {source} (Score: {score:.4f})")
        # Print snippet
        snippet = res.get('document', '')[:200].replace('\n', ' ')
        print(f"   {snippet}...")
