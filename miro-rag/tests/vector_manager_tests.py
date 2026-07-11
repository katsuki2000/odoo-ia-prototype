"""Shared unit tests for vector store manager implementations."""


class VectorManagerTestMixin:
    """Behavioral contract shared by ChromaManager and QdrantManager."""

    def test_initialization(self):
        self.assertIsNotNone(self.manager)
        self.assertEqual(self.manager.collection_name, "test_collection")

    def test_add_chunks_simple(self):
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
        self.assertTrue(all(isinstance(chunk_id, str) for chunk_id in ids))

    def test_add_chunks_with_ids(self):
        texts = ["Chunk text"]
        metadatas = [{"source": "test.py", "type": "code_python"}]
        ids = ["custom_id_1"]

        result_ids = self.manager.add_chunks(texts, metadatas, ids)

        self.assertEqual(result_ids, ["custom_id_1"])

    def test_add_chunks_metadata_validation(self):
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
                "nested_data": {"key": "value"},
                "list_data": [1, 2, 3],
            }
        ]

        ids = self.manager.add_chunks(texts, metadatas)
        self.assertEqual(len(ids), 1)

    def test_add_chunks_mismatch_error(self):
        texts = ["Text 1", "Text 2"]
        metadatas = [{"source": "doc1.pdf", "type": "doc_pdf"}]

        with self.assertRaises(ValueError):
            self.manager.add_chunks(texts, metadatas)

    def test_query(self):
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

        results = self.manager.query("sales process", top_k=2)

        self.assertEqual(results["count"], 2)
        self.assertTrue(len(results["results"]) <= 2)
        self.assertTrue(all("document" in result for result in results["results"]))
        self.assertTrue(all("metadata" in result for result in results["results"]))
        self.assertTrue(all("similarity" in result for result in results["results"]))

    def test_query_with_filter(self):
        texts = [
            "Python implementation details.",
            "XML template structure.",
            "PDF documentation.",
        ]
        metadatas = [
            {"source": "code.py", "type": "code_python", "module": "account"},
            {"source": "templates.xml", "type": "code_xml", "module": "sale"},
            {"source": "docs.pdf", "type": "doc_pdf", "module": "stock"},
        ]

        self.manager.add_chunks(texts, metadatas)

        results = self.manager.query(
            "code implementation",
            top_k=10,
            where={"type": {"$eq": "code_python"}},
        )

        for result in results["results"]:
            self.assertEqual(result["metadata"]["type"], "code_python")

    def test_get_by_id(self):
        texts = ["Test chunk content"]
        metadatas = [{"source": "test.pdf", "type": "doc_pdf"}]
        ids = ["test_id_123"]

        self.manager.add_chunks(texts, metadatas, ids)

        result = self.manager.get_by_id("test_id_123")

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "test_id_123")
        self.assertEqual(result["document"], "Test chunk content")

    def test_get_by_id_not_found(self):
        result = self.manager.get_by_id("non_existent_id")
        self.assertIsNone(result)

    def test_delete_by_source(self):
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

        deleted_count = self.manager.delete_by_source("file1.pdf")

        self.assertEqual(deleted_count, 2)

        results = self.manager.query("file2", top_k=10)
        self.assertGreater(results["count"], 0)

    def test_delete_by_ids(self):
        texts = ["Chunk 1", "Chunk 2", "Chunk 3"]
        metadatas = [
            {"source": "doc.pdf", "type": "doc_pdf"},
            {"source": "doc.pdf", "type": "doc_pdf"},
            {"source": "doc.pdf", "type": "doc_pdf"},
        ]

        ids = self.manager.add_chunks(texts, metadatas)

        deleted_count = self.manager.delete_by_ids(ids[:2])

        self.assertEqual(deleted_count, 2)

        result = self.manager.get_by_id(ids[2])
        self.assertIsNotNone(result)

    def test_delete_by_ids_empty(self):
        result = self.manager.delete_by_ids([])
        self.assertEqual(result, 0)

    def test_get_stats_empty(self):
        stats = self.manager.get_stats()

        self.assertEqual(stats["total_chunks"], 0)
        self.assertEqual(stats["by_type"]["code_python"], 0)
        self.assertEqual(stats["by_type"]["code_xml"], 0)
        self.assertEqual(stats["by_type"]["doc_pdf"], 0)
        self.assertEqual(stats["by_type"]["doc_wiki"], 0)

    def test_get_stats_populated(self):
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
        texts = ["Test chunk"]
        metadatas = [{"source": "test.pdf", "type": "doc_pdf"}]

        self.manager.add_chunks(texts, metadatas)

        stats = self.manager.get_stats()
        self.assertEqual(stats["total_chunks"], 1)

        self.manager.delete_collection()

        stats = self.manager.get_stats()
        self.assertEqual(stats["total_chunks"], 0)

    def test_clean_metadata(self):
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

        cleaned = self.manager.__class__._clean_metadata(metadata)

        self.assertEqual(cleaned["string"], "value")
        self.assertEqual(cleaned["integer"], 42)
        self.assertEqual(cleaned["float"], 3.14)
        self.assertEqual(cleaned["boolean"], True)
        self.assertNotIn("none_value", cleaned)
        self.assertIsInstance(cleaned["dict"], str)
        self.assertIsInstance(cleaned["list"], str)
        self.assertIsInstance(cleaned["complex"], str)
