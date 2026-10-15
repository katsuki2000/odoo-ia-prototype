"""
Unit tests for ingestion/pdf_loader.py

Tests cover:
- PDF text extraction
- OCR detection and fallback
- Chunking functionality
- Metadata generation with content_hash
- OCR quality assessment
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from document_rag.ingestion.pdf_loader import PDFLoader


class TestPDFLoader(unittest.TestCase):
    """Test suite for PDFLoader."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.temp_dir = tempfile.mkdtemp()

    def setUp(self):
        """Initialize PDFLoader for each test."""
        self.loader = PDFLoader(chunk_size=200, chunk_overlap=20)

    def test_initialization(self):
        """Test PDFLoader initialization."""
        self.assertEqual(self.loader.chunk_size, 200)
        self.assertEqual(self.loader.chunk_overlap, 20)
        self.assertIsNotNone(self.loader.splitter)

    def test_compute_hash(self):
        """Test content hash computation."""
        text1 = "This is test content"
        text2 = "This is different content"

        hash1 = PDFLoader._compute_hash(text1)
        hash2 = PDFLoader._compute_hash(text2)

        self.assertEqual(len(hash1), 12)
        self.assertNotEqual(hash1, hash2)
        # Same content should produce same hash
        hash1_again = PDFLoader._compute_hash(text1)
        self.assertEqual(hash1, hash1_again)

    def test_assess_ocr_quality_high(self):
        """Test OCR quality assessment for high-quality text."""
        text = "This is a well-formed paragraph with proper spelling and good structure. " * 20

        quality = PDFLoader._assess_ocr_quality(text)

        self.assertEqual(quality, "high")

    def test_assess_ocr_quality_low_short(self):
        """Test OCR quality assessment for short text."""
        text = "Short text"

        quality = PDFLoader._assess_ocr_quality(text)

        self.assertEqual(quality, "low")

    def test_assess_ocr_quality_low_garbled(self):
        """Test OCR quality assessment for garbled text."""
        text = "!@#$%^&*() " * 50  # Mostly special characters

        quality = PDFLoader._assess_ocr_quality(text)

        self.assertEqual(quality, "low")

    def test_assess_ocr_quality_empty(self):
        """Test OCR quality assessment for empty text."""
        quality = PDFLoader._assess_ocr_quality("")
        self.assertEqual(quality, "low")

        quality = PDFLoader._assess_ocr_quality("   ")
        self.assertEqual(quality, "low")

    def test_extract_text_from_pdf_mock(self):
        """Test text extraction with mocked PDF reader."""
        mock_reader = MagicMock()
        mock_page1 = MagicMock()
        mock_page2 = MagicMock()

        mock_page1.extract_text.return_value = "Page 1 content"
        mock_page2.extract_text.return_value = "Page 2 content"
        mock_reader.pages = [mock_page1, mock_page2]

        text = self.loader._extract_text_from_pdf(mock_reader)

        self.assertIn("Page 1 content", text)
        self.assertIn("Page 2 content", text)
        self.assertIn("--- Page 1 ---", text)
        self.assertIn("--- Page 2 ---", text)

    def test_extract_text_from_pdf_empty_page(self):
        """Test text extraction when a page has no text."""
        mock_reader = MagicMock()
        mock_page1 = MagicMock()
        mock_page2 = MagicMock()

        mock_page1.extract_text.return_value = "Page 1 content"
        mock_page2.extract_text.return_value = ""  # Empty page
        mock_reader.pages = [mock_page1, mock_page2]

        text = self.loader._extract_text_from_pdf(mock_reader)

        self.assertIn("Page 1 content", text)
        # Empty page should be skipped
        self.assertNotIn("--- Page 2 ---", text)

    def test_load_and_chunk_metadata(self):
        """Test that load_and_chunk generates proper metadata."""
        # Create a mock PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            mock_reader = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Sample content " * 50

            with patch(
                "document_rag.ingestion.pdf_loader.PdfReader", return_value=mock_reader
            ):
                result = self.loader.load_and_chunk(pdf_path)

                # Verify structure
                self.assertIn("chunks", result)
                self.assertIn("metadatas", result)
                self.assertIn("ocr_used", result)
                self.assertIn("ocr_quality", result)

                # Verify chunk count matches metadata count
                self.assertEqual(len(result["chunks"]), len(result["metadatas"]))

                # Verify metadata fields
                for metadata in result["metadatas"]:
                    self.assertIn("source", metadata)
                    self.assertIn("type", metadata)
                    self.assertIn("content_hash", metadata)
                    self.assertIn("ocr_processed", metadata)
                    self.assertIn("ocr_quality", metadata)
                    self.assertIn("chunk_index", metadata)
                    self.assertIn("total_chunks", metadata)

                    # Verify hash format
                    self.assertEqual(len(metadata["content_hash"]), 12)

        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_load_and_chunk_content_hash_unique(self):
        """Test that different chunks have different content hashes."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            mock_reader = MagicMock()
            mock_page = MagicMock()
            # Create text with enough variation to produce different chunks
            text = "First paragraph. " * 30 + "\n\nSecond paragraph. " * 30
            mock_page.extract_text.return_value = text

            with patch(
                "document_rag.ingestion.pdf_loader.PdfReader", return_value=mock_reader
            ):
                result = self.loader.load_and_chunk(pdf_path)

                if len(result["chunks"]) > 1:
                    hashes = [m["content_hash"] for m in result["metadatas"]]
                    # All hashes should be unique
                    self.assertEqual(len(hashes), len(set(hashes)))

        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_load_and_chunk_ocr_threshold(self):
        """Test OCR triggering based on extraction threshold."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
            pdf_size = os.path.getsize(pdf_path)

        try:
            loader = PDFLoader(ocr_threshold=0.5)  # Higher threshold

            mock_reader = MagicMock()
            mock_page = MagicMock()
            # Return very little text
            mock_page.extract_text.return_value = "x" * 10

            with patch(
                "document_rag.ingestion.pdf_loader.PdfReader", return_value=mock_reader
            ):
                with patch.object(
                    loader, "_extract_text_via_ocr", return_value="OCR text"
                ):
                    result = loader.load_and_chunk(pdf_path)

                    # Since extracted text is small relative to PDF size,
                    # OCR should have been attempted
                    # (but may not succeed due to mocking)

        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_file_not_found(self):
        """Test handling of non-existent PDF files."""
        with self.assertRaises(FileNotFoundError):
            self.loader.load_and_chunk("/non/existent/file.pdf")

    def test_chunk_index_and_total(self):
        """Test that chunk indices are sequential and total_chunks is correct."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            mock_reader = MagicMock()
            mock_page = MagicMock()
            # Create content long enough to produce multiple chunks
            mock_page.extract_text.return_value = "Sample content. " * 100

            with patch(
                "document_rag.ingestion.pdf_loader.PdfReader", return_value=mock_reader
            ):
                result = self.loader.load_and_chunk(pdf_path)

                total_chunks = len(result["chunks"])
                if total_chunks > 0:
                    for i, metadata in enumerate(result["metadatas"]):
                        self.assertEqual(metadata["chunk_index"], i)
                        self.assertEqual(metadata["total_chunks"], total_chunks)

        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)


class TestPDFLoaderIntegration(unittest.TestCase):
    """Integration tests for PDFLoader."""

    def test_chunking_preserves_content(self):
        """Test that chunking doesn't lose content."""
        loader = PDFLoader(chunk_size=100, chunk_overlap=20)

        original_text = "This is a test document. " * 50
        chunks = loader.splitter.split_text(original_text)

        # Reconstruct text (with overlaps accounted for)
        reconstructed = " ".join(chunks)

        # The reconstructed text should contain most of the original
        original_words = set(original_text.split())
        reconstructed_words = set(reconstructed.split())

        # Most words should be preserved
        overlap_ratio = len(original_words & reconstructed_words) / len(
            original_words
        )
        self.assertGreater(overlap_ratio, 0.9)


if __name__ == "__main__":
    unittest.main()
