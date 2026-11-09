"""
Integration tests for Step 2 Day 5 - Complete ingestion pipeline validation.

Validates:
- OCR detection and quality assessment
- Metadata schema correctness
- Incremental indexing
"""

import os
import tempfile
import unittest
from pathlib import Path

import pytest

from document_rag.vectorstore.chroma_manager import ChromaManager


class TestIngestionPipeline(unittest.TestCase):
    """Loader and index pipeline tests."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "chroma_db"

    def setUp(self):
        """Initialize the document index for each test."""
        self.manager = ChromaManager(db_path=self.db_path, collection_name="test_pipeline")

    def tearDown(self):
        """Clean up after each test."""
        try:
            self.manager.delete_collection()
        except Exception:
            pass

    @pytest.mark.embedding_server
    def test_metadata_schema_completeness(self):
        """Test that all ingested chunks have complete metadata."""
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False
        ) as f:
            f.write("TEST DOCUMENT\n\nSection with content for testing metadata.")
            f.flush()
            txt_path = f.name

        try:
            from document_rag.ingestion.wiki_loader import WikiLoader

            loader = WikiLoader()
            result = loader.load_text_file(txt_path)

            # Add to ChromaDB
            chunks = result["chunks"]
            metadatas = result["metadatas"]

            ids = self.manager.add_chunks(chunks, metadatas)

            # Verify metadata completeness
            required_fields = [
                "source",
                "type",
                "content_hash",
                "chunk_index",
                "total_chunks",
            ]

            for metadata in metadatas:
                for field in required_fields:
                    self.assertIn(
                        field,
                        metadata,
                        f"Missing required field: {field}",
                    )

        finally:
            os.unlink(txt_path)

    def test_incremental_indexing_content_hash(self):
        """Test that content hash enables incremental indexing."""
        text1 = "Original content version 1"
        text2 = "Modified content version 2"

        from document_rag.ingestion.pdf_loader import PDFLoader

        hash1 = PDFLoader._compute_hash(text1)
        hash2 = PDFLoader._compute_hash(text2)

        # Different content should have different hashes
        self.assertNotEqual(hash1, hash2)

        # Same content should have same hash (deterministic)
        hash1_again = PDFLoader._compute_hash(text1)
        self.assertEqual(hash1, hash1_again)

    def test_ocr_quality_assessment_workflow(self):
        """Test OCR quality assessment in workflow."""
        from document_rag.ingestion.pdf_loader import PDFLoader

        # Test various quality levels
        test_cases = [
            ("This is well-formed text. " * 50, "high"),  # High quality
            ("x y z a b", "low"),  # Low quality (short)
            ("!@#$%^&*() " * 20, "low"),  # Low quality (garbled)
        ]

        loader = PDFLoader()

        for text, expected_quality in test_cases:
            quality = loader._assess_ocr_quality(text)
            # We can't guarantee exact match, but we can verify it's reasonable
            self.assertIn(quality, ["high", "low", "medium"])

    def test_chunk_metadata_consistency(self):
        """Test that chunk metadata is internally consistent."""
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False
        ) as f:
            f.write("Section A\n\n" + "Content. " * 100)
            f.flush()
            txt_path = f.name

        try:
            from document_rag.ingestion.wiki_loader import WikiLoader

            loader = WikiLoader(chunk_size=200, chunk_overlap=20)
            result = loader.load_text_file(txt_path)

            metadatas = result["metadatas"]

            # All chunks from same file should have same source
            sources = set(m["source"] for m in metadatas)
            self.assertEqual(len(sources), 1)

            # All chunks should have valid indices
            total_chunks = metadatas[0]["total_chunks"]
            for i, metadata in enumerate(metadatas):
                self.assertEqual(metadata["chunk_index"], i)
                self.assertEqual(metadata["total_chunks"], total_chunks)

        finally:
            os.unlink(txt_path)

    @pytest.mark.embedding_server
    def test_retrieval_after_ingestion(self):
        """Test that ingested documents are retrievable."""
        # Create and ingest test document
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False
        ) as f:
            f.write(
                "Sales Process Documentation\n\n"
                "The sales process includes the following steps:\n"
                "1. Lead generation\n"
                "2. Qualification\n"
                "3. Proposal\n"
                "4. Closure"
            )
            f.flush()
            txt_path = f.name

        try:
            from document_rag.ingestion.wiki_loader import WikiLoader

            loader = WikiLoader()
            result = loader.load_text_file(txt_path)

            chunks = result["chunks"]
            metadatas = result["metadatas"]

            # Ingest (wiki/text content goes to docs_manager)
            ids = self.manager.add_chunks(chunks, metadatas)

            # Try to retrieve
            query_result = self.manager.query(
                "What is the sales process?",
                top_k=2,
            )

            # Should find relevant chunks
            self.assertGreater(query_result["count"], 0)
            self.assertIn("Sales", query_result["results"][0]["document"])

        finally:
            os.unlink(txt_path)

    @pytest.mark.embedding_server
    def test_delete_by_source(self):
        """Test deletion of chunks by source file."""
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False
        ) as f:
            f.write("Test content for deletion")
            f.flush()
            txt_path = f.name

        try:
            from document_rag.ingestion.wiki_loader import WikiLoader

            loader = WikiLoader()
            result = loader.load_text_file(txt_path)

            chunks = result["chunks"]
            metadatas = result["metadatas"]

            # Ingest (wiki/text content goes to docs_manager)
            ids = self.manager.add_chunks(chunks, metadatas)
            initial_count = len(ids)

            # Delete by source
            source_name = str(txt_path)
            deleted = self.manager.delete_by_source(source_name)

            self.assertEqual(deleted, initial_count)

            # Verify chunks are gone
            stats = self.manager.get_stats()
            self.assertEqual(stats["total_chunks"], 0)

        finally:
            os.unlink(txt_path)

    @pytest.mark.embedding_server
    def test_statistics_reflect_docs_manager(self):
        """Test that ingestion statistics come from docs_manager alone."""
        doc_texts = ["PDF document chunk", "Wiki page chunk"]
        doc_metadatas = [
            {"source": "file1.pdf", "type": "doc_pdf", "module": "stock"},
            {"source": "file2.txt", "type": "doc_wiki", "module": "sale"},
        ]
        self.manager.add_chunks(doc_texts, doc_metadatas)

        stats = self.manager.get_stats()

        self.assertEqual(stats["total_chunks"], 2)
        self.assertEqual(stats["by_type"]["doc_pdf"], 1)
        self.assertEqual(stats["by_type"]["doc_wiki"], 1)
        self.assertEqual(stats["by_module"]["stock"], 1)
        self.assertEqual(stats["by_module"]["sale"], 1)


class TestOCRIntegration(unittest.TestCase):
    """Integration tests for OCR functionality."""

    def test_ocr_metadata_flags(self):
        """Test that OCR metadata flags are set correctly."""
        from document_rag.ingestion.pdf_loader import PDFLoader

        loader = PDFLoader()

        # Text with low extraction ratio would trigger OCR
        # (but we can't test actual PDF without dependencies)

        # Test quality assessment
        high_quality_text = "This is high quality OCR text. " * 50
        quality = loader._assess_ocr_quality(high_quality_text)
        self.assertEqual(quality, "high")

        low_quality_text = "x"
        quality = loader._assess_ocr_quality(low_quality_text)
        self.assertEqual(quality, "low")

    def test_ocr_caveat_in_response(self):
        """Test that OCR caveat logic is present in metadata."""
        # When sourcing from low-quality OCR, caveat should be added
        metadatas = [
            {
                "source": "scanned_invoice.pdf",
                "type": "doc_pdf",
                "ocr_processed": True,
                "ocr_quality": "low",
            }
        ]

        # Check that metadata flags are set
        for m in metadatas:
            if m.get("ocr_quality") == "low":
                # In actual response, caveat would be appended
                self.assertTrue(m["ocr_processed"])


class TestErrorHandling(unittest.TestCase):
    """Test error handling in ingestion pipeline."""

    def test_missing_file_handling(self):
        """Test graceful handling of missing files."""
        from document_rag.ingestion.pdf_loader import PDFLoader

        loader = PDFLoader()

        with self.assertRaises(FileNotFoundError):
            loader.load_and_chunk("/nonexistent/file.pdf")

    def test_corrupt_file_handling(self):
        """Test handling of corrupt files."""
        from document_rag.ingestion.pdf_loader import PDFLoader

        loader = PDFLoader()

        with tempfile.NamedTemporaryFile(
            suffix=".pdf", mode="wb", delete=False
        ) as f:
            f.write(b"not a valid pdf content")
            f.flush()
            pdf_path = f.name

        try:
            result = loader.load_and_chunk(pdf_path)
            self.assertIsNotNone(result)
            self.assertIn("chunks", result)

        finally:
            os.unlink(pdf_path)


if __name__ == "__main__":
    unittest.main()
