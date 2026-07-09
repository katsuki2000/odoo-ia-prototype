"""
Unit tests for vectorstore/chroma_manager.py

Tests cover:
- Chunk addition with metadata
- Query functionality
- Deletion operations (by source and by ID)
- Collection statistics
- Metadata validation
"""

import os
import tempfile
import unittest
from pathlib import Path

from vectorstore.chroma_manager import ChromaManager


class TestChromaManager(unittest.TestCase):
    """Test suite for ChromaManager."""

    @classmethod
    def setUpClass(cls):
        """Create a temporary database for testing."""
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "test_chroma"

    def setUp(self):
        """Initialize a fresh ChromaManager instance for each test."""
        self.manager = ChromaManager(
            db_path=self.db_path,
            collection_name="test_collection"
        )

    def tearDown(self):
        """Clean up collection after each test."""
        try:
            self.manager.delete_collection()
        except Exception:
            pass

    def test_initialization(self):
        """Test ChromaManager initialization."""
        self.assertIsNotNone(self.manager.client)
        self.assertIsNotNone(self.manager.collection)
        self.assertEqual(self.manager.collection_name, "test_collection")

    def test_add_chunks_simple(self):
        """Test adding simple chunks without IDs."""
        texts = [
            "This is the first chunk.",
            "This is the second chunk.",
        ]
        metadatas = [
            {"source": "doc1.pdf", "type": "doc_pdf", "module": "account"},
            {"source": "doc2.pdf", "type": "doc_pdf", "module": "sale"},
        ]

        ids = self.manager.add_chunks(texts, metadatas)

        self.assertEqual(len(ids), 2)
        self.assertTrue(all(isinstance(id, str) for id in ids))

    def test_add_chunks_with_ids(self):
        """Test adding chunks with explicit IDs."""
        texts = ["Chunk text"]
        metadatas = [{"source": "test.py", "type": "code_python"}]
        ids = ["custom_id_1"]

        result_ids = self.manager.add_chunks(texts, metadatas, ids)

        self.assertEqual(result_ids, ["custom_id_1"])

    def test_add_chunks_metadata_validation(self):
        """Test that metadata is properly validated and cleaned."""
        texts = ["Test chunk"]
        metadatas = [
            {
                "source": "file.pdf",
                "type": "doc_pdf",
                "module": "account",
                "lines": "10-50",
                "class": "MyClass",
                "function": "my_func",
                "content_hash": "abc123",
                "ocr_processed": True,
                "ocr_quality": "high",
                "nested_data": {"key": "value"},  # Should be converted to JSON string
                "list_data": [1, 2, 3],  # Should be converted to JSON string
            }
        ]

        ids = self.manager.add_chunks(texts, metadatas)
        self.assertEqual(len(ids), 1)

    def test_add_chunks_mismatch_error(self):
        """Test that mismatched texts and metadatas raise an error."""
        texts = ["Text 1", "Text 2"]
        metadatas = [{"source": "doc1.pdf", "type": "doc_pdf"}]  # Only one metadata

        with self.assertRaises(ValueError):
            self.manager.add_chunks(texts, metadatas)

    def test_query(self):
        """Test querying chunks."""
        texts = [
            "This document discusses sales processes in detail.",
            "Stock management is handled by the inventory module.",
            "Account reconciliation requires careful attention.",
        ]
        metadatas = [
            {"source": "sales.md", "type": "doc_wiki", "module": "sale"},
            {"source": "stock.md", "type": "doc_wiki", "module": "stock"},
            {"source": "account.md", "type": "doc_wiki", "module": "account"},
        ]

        self.manager.add_chunks(texts, metadatas)

        # Query for sales-related content
        results = self.manager.query("sales process", top_k=2)

        self.assertEqual(results["count"], 2)
        self.assertTrue(len(results["results"]) <= 2)
        self.assertTrue(all("document" in r for r in results["results"]))
        self.assertTrue(all("metadata" in r for r in results["results"]))
        self.assertTrue(all("similarity" in r for r in results["results"]))

    def test_query_with_filter(self):
        """Test querying with metadata filters."""
        texts = [
            "Python implementation details.",
            "XML template structure.",
            "PDF documentation."
        ]
        metadatas = [
            {"source": "code.py", "type": "code_python", "module": "account"},
            {"source": "templates.xml", "type": "code_xml", "module": "sale"},
            {"source": "docs.pdf", "type": "doc_pdf", "module": "stock"},
        ]

        self.manager.add_chunks(texts, metadatas)

        # Query only Python files
        results = self.manager.query(
            "code implementation",
            top_k=10,
            where={"type": {"$eq": "code_python"}}
        )

        # Should return Python-only results
        for result in results["results"]:
            self.assertEqual(result["metadata"]["type"], "code_python")

    def test_get_by_id(self):
        """Test retrieving a chunk by ID."""
        texts = ["Test chunk content"]
        metadatas = [{"source": "test.pdf", "type": "doc_pdf"}]
        ids = ["test_id_123"]

        self.manager.add_chunks(texts, metadatas, ids)

        result = self.manager.get_by_id("test_id_123")

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "test_id_123")
        self.assertEqual(result["document"], "Test chunk content")

    def test_get_by_id_not_found(self):
        """Test getting a non-existent chunk."""
        result = self.manager.get_by_id("non_existent_id")
        self.assertIsNone(result)

    def test_delete_by_source(self):
        """Test deleting chunks by source."""
        texts = [
            "Chunk 1 from file1",
            "Chunk 2 from file1",
            "Chunk 1 from file2",
        ]
        metadatas = [
            {"source": "file1.pdf", "type": "doc_pdf"},
            {"source": "file1.pdf", "type": "doc_pdf"},
            {"source": "file2.pdf", "type": "doc_pdf"},
        ]

        self.manager.add_chunks(texts, metadatas)

        # Delete file1
        deleted_count = self.manager.delete_by_source("file1.pdf")

        self.assertEqual(deleted_count, 2)

        # Verify file2 still exists
        results = self.manager.query("file2", top_k=10)
        self.assertGreater(results["count"], 0)

    def test_delete_by_ids(self):
        """Test deleting chunks by ID."""
        texts = ["Chunk 1", "Chunk 2", "Chunk 3"]
        metadatas = [
            {"source": "doc.pdf", "type": "doc_pdf"},
            {"source": "doc.pdf", "type": "doc_pdf"},
            {"source": "doc.pdf", "type": "doc_pdf"},
        ]

        ids = self.manager.add_chunks(texts, metadatas)

        # Delete first two chunks
        deleted_count = self.manager.delete_by_ids(ids[:2])

        self.assertEqual(deleted_count, 2)

        # Verify third chunk still exists
        result = self.manager.get_by_id(ids[2])
        self.assertIsNotNone(result)

    def test_delete_by_ids_empty(self):
        """Test delete_by_ids with empty list."""
        result = self.manager.delete_by_ids([])
        self.assertEqual(result, 0)

    def test_get_stats_empty(self):
        """Test getting stats from empty collection."""
        stats = self.manager.get_stats()

        self.assertEqual(stats["total_chunks"], 0)
        self.assertEqual(stats["by_type"]["code_python"], 0)
        self.assertEqual(stats["by_type"]["code_xml"], 0)
        self.assertEqual(stats["by_type"]["doc_pdf"], 0)
        self.assertEqual(stats["by_type"]["doc_wiki"], 0)

    def test_get_stats_populated(self):
        """Test getting stats from populated collection."""
        texts = [
            "Python code", "Python code", "Python code",
            "XML template", "XML template",
            "PDF document",
            "Wiki article",
        ]
        metadatas = [
            {"source": "file1.py", "type": "code_python", "module": "account"},
            {"source": "file2.py", "type": "code_python", "module": "account"},
            {"source": "file3.py", "type": "code_python", "module": "sale"},
            {"source": "template1.xml", "type": "code_xml", "module": "account"},
            {"source": "template2.xml", "type": "code_xml", "module": "sale"},
            {"source": "doc.pdf", "type": "doc_pdf", "module": "stock"},
            {"source": "wiki.md", "type": "doc_wiki", "module": "account"},
        ]

        self.manager.add_chunks(texts, metadatas)

        stats = self.manager.get_stats()

        self.assertEqual(stats["total_chunks"], 7)
        self.assertEqual(stats["by_type"]["code_python"], 3)
        self.assertEqual(stats["by_type"]["code_xml"], 2)
        self.assertEqual(stats["by_type"]["doc_pdf"], 1)
        self.assertEqual(stats["by_type"]["doc_wiki"], 1)
        self.assertEqual(stats["by_module"]["account"], 4)
        self.assertEqual(stats["by_module"]["sale"], 2)
        self.assertEqual(stats["by_module"]["stock"], 1)

    def test_delete_collection(self):
        """Test deleting and recreating a collection."""
        texts = ["Test chunk"]
        metadatas = [{"source": "test.pdf", "type": "doc_pdf"}]

        self.manager.add_chunks(texts, metadatas)

        # Verify chunks exist
        stats = self.manager.get_stats()
        self.assertEqual(stats["total_chunks"], 1)

        # Delete collection
        self.manager.delete_collection()

        # Verify collection is empty
        stats = self.manager.get_stats()
        self.assertEqual(stats["total_chunks"], 0)

    def test_clean_metadata(self):
        """Test metadata cleaning."""
        metadata = {
            "string": "value",
            "integer": 42,
            "float": 3.14,
            "boolean": True,
            "none_value": None,
            "dict": {"nested": "value"},
            "list": [1, 2, 3],
            "complex": object(),
        }

        cleaned = ChromaManager._clean_metadata(metadata)

        self.assertEqual(cleaned["string"], "value")
        self.assertEqual(cleaned["integer"], 42)
        self.assertEqual(cleaned["float"], 3.14)
        self.assertEqual(cleaned["boolean"], True)
        self.assertNotIn("none_value", cleaned)  # None values are skipped
        self.assertIsInstance(cleaned["dict"], str)  # Dict converted to JSON string
        self.assertIsInstance(cleaned["list"], str)  # List converted to JSON string
        self.assertIsInstance(cleaned["complex"], str)  # Complex object converted to string


if __name__ == "__main__":
    unittest.main()
