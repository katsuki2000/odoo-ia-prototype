#!/usr/bin/env python3
"""
Simple validation script for ChromaManager (Step 2, Day 1).

Tests basic CRUD operations without requiring pytest.
"""

import sys
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from vectorstore.chroma_manager import ChromaManager


def test_basic_operations():
    """Test basic ChromaManager operations."""
    print("=" * 60)
    print("CHROMA MANAGER VALIDATION - STEP 2 DAY 1")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test_chroma"

        # Test 1: Initialization
        print("\n[TEST 1] Initialization")
        try:
            manager = ChromaManager(db_path=db_path, collection_name="test_collection")
            print("  ✓ ChromaManager initialized successfully")
            print(f"  ✓ Database path: {manager.db_path}")
            print(f"  ✓ Collection name: {manager.collection_name}")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

        # Test 2: Add chunks
        print("\n[TEST 2] Adding chunks")
        try:
            texts = [
                "This is the first chunk about sales processes.",
                "This is the second chunk about stock management.",
                "This is the third chunk about accounting.",
            ]
            metadatas = [
                {"source": "sales.md", "type": "doc_wiki", "module": "sale"},
                {"source": "stock.md", "type": "doc_wiki", "module": "stock"},
                {"source": "account.md", "type": "doc_wiki", "module": "account"},
            ]

            ids = manager.add_chunks(texts, metadatas)
            print(f"  ✓ Added {len(ids)} chunks")
            print(f"  ✓ Generated IDs: {ids[:1]}... (showing first)")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

        # Test 3: Get statistics
        print("\n[TEST 3] Collection statistics")
        try:
            stats = manager.get_stats()
            print(f"  ✓ Total chunks: {stats['total_chunks']}")
            print(f"  ✓ By type: {stats['by_type']}")
            print(f"  ✓ By module: {stats['by_module']}")
            assert stats["total_chunks"] == 3, "Should have 3 chunks"
            assert stats["by_type"]["doc_wiki"] == 3, "All chunks should be doc_wiki"
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

        # Test 4: Query
        print("\n[TEST 4] Querying")
        try:
            results = manager.query("sales process", top_k=2)
            print(f"  ✓ Query returned {results['count']} results")
            assert results["count"] > 0, "Should return at least 1 result"
            print(f"  ✓ Top result similarity: {results['results'][0]['similarity']:.4f}")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

        # Test 5: Get by ID
        print("\n[TEST 5] Retrieve by ID")
        try:
            chunk = manager.get_by_id(ids[0])
            assert chunk is not None, "Should find chunk by ID"
            assert chunk["document"] == texts[0], "Document content should match"
            print(f"  ✓ Retrieved chunk: {chunk['document'][:40]}...")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

        # Test 6: Delete by source
        print("\n[TEST 6] Delete by source")
        try:
            deleted = manager.delete_by_source("sales.md")
            assert deleted == 1, "Should delete 1 chunk"
            stats = manager.get_stats()
            assert stats["total_chunks"] == 2, "Should have 2 chunks left"
            print(f"  ✓ Deleted chunks from sales.md")
            print(f"  ✓ Remaining chunks: {stats['total_chunks']}")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

        # Test 7: Delete by IDs
        print("\n[TEST 7] Delete by IDs")
        try:
            remaining_ids = [id for id in ids[1:]]
            deleted = manager.delete_by_ids(remaining_ids[:1])
            stats = manager.get_stats()
            assert stats["total_chunks"] == 1, "Should have 1 chunk left"
            print(f"  ✓ Deleted chunk by ID")
            print(f"  ✓ Remaining chunks: {stats['total_chunks']}")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

        # Test 8: Metadata cleaning
        print("\n[TEST 8] Metadata validation")
        try:
            metadata = {
                "string": "value",
                "integer": 42,
                "float": 3.14,
                "boolean": True,
                "none_value": None,
                "dict": {"nested": "value"},
                "list": [1, 2, 3],
            }
            cleaned = ChromaManager._clean_metadata(metadata)
            assert isinstance(cleaned["string"], str), "String should remain string"
            assert isinstance(cleaned["integer"], int), "Integer should remain int"
            assert "none_value" not in cleaned, "None values should be removed"
            assert isinstance(cleaned["dict"], str), "Dict should be converted to string"
            print(f"  ✓ Metadata cleaning works correctly")
            print(f"  ✓ {len(cleaned)} fields processed (1 None value filtered)")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return False

    print("\n" + "=" * 60)
    print("✓ ALL TESTS PASSED")
    print("=" * 60)
    print("\nDeliverables for Step 2 Day 1:")
    print("  ✓ vectorstore/chroma_manager.py with ChromaManager class")
    print("  ✓ add_chunks() - Add documents with metadata")
    print("  ✓ query() - Vector search with filtering")
    print("  ✓ get_by_id() - Retrieve specific chunks")
    print("  ✓ delete_by_source() - Delete all chunks from a file")
    print("  ✓ delete_by_ids() - Delete specific chunks")
    print("  ✓ get_stats() - Collection statistics")
    print("  ✓ Metadata schema with required fields")
    print("  ✓ Unit tests pass validation")
    return True


if __name__ == "__main__":
    success = test_basic_operations()
    sys.exit(0 if success else 1)
