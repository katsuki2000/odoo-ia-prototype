"""
PDF document loader with OCR support for scanned PDFs.

Handles both text-based and image-based PDFs:
- Text-based PDFs: Direct text extraction via pypdf
- Image-based PDFs: OCR via pytesseract (French + English)

Chunks documents with RecursiveCharacterTextSplitter (512 tokens, 50 overlap).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from PIL import Image
    import io
except ImportError:
    Image = None
    io = None

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class PDFLoader:
    """Loads and processes PDF documents with automatic OCR detection."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        ocr_threshold: float = 0.1,
    ):
        """
        Initialize PDF loader.

        Args:
            chunk_size: Number of characters per chunk
            chunk_overlap: Number of overlapping characters between chunks
            ocr_threshold: Minimum ratio of text extracted before triggering OCR
                          (if extracted_text_length / pdf_size < threshold, use OCR)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.ocr_threshold = ocr_threshold

        # Initialize text splitter (token-based via tiktoken)
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

        # Verify dependencies
        if not PdfReader:
            logger.warning("pypdf not installed - PDF loading will fail")
        if not pytesseract:
            logger.warning("pytesseract not installed - OCR will be skipped")
        if not Image:
            logger.warning("Pillow not installed - Image conversion will fail")

    def load_and_chunk(
        self,
        pdf_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Load a PDF and chunk it with OCR detection.

        Args:
            pdf_path: Path to PDF file
            metadata: Optional metadata to add to all chunks

        Returns:
            Dictionary with:
            - chunks: List of text chunks
            - metadatas: List of metadata dictionaries
            - ocr_used: Whether OCR was used
            - ocr_quality: "high", "low", or None
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        if not PdfReader:
            raise ImportError("pypdf is required for PDF loading")

        # Initialize metadata
        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(pdf_path))
        base_metadata.setdefault("type", "doc_pdf")
        base_metadata["file_size"] = pdf_path.stat().st_size

        # Step 1: Try to extract text with pypdf
        logger.info(f"Loading PDF: {pdf_path}")
        try:
            reader = PdfReader(str(pdf_path))
            text = self._extract_text_from_pdf(reader)
            ocr_used = False
            ocr_quality = None
        except Exception as e:
            logger.warning(f"Error extracting text from {pdf_path}: {e}")
            text = ""
            ocr_used = False
            ocr_quality = None

        # Step 2: Decide if OCR is needed
        pdf_size = base_metadata.get("file_size", 1)
        text_extracted_ratio = len(text) / pdf_size if pdf_size > 0 else 0

        if text_extracted_ratio < self.ocr_threshold:
            logger.info(
                f"Low text extraction ratio ({text_extracted_ratio:.2%}), attempting OCR"
            )
            if pytesseract and Image:
                ocr_text = self._extract_text_via_ocr(pdf_path)
                if ocr_text and len(ocr_text) > len(text):
                    text = ocr_text
                    ocr_used = True
                    ocr_quality = self._assess_ocr_quality(text)
                    logger.info(f"OCR extraction complete. Quality: {ocr_quality}")
            else:
                logger.warning("pytesseract or Pillow not installed, skipping OCR")

        # Step 3: Chunk the text
        if text.strip():
            chunks = self.splitter.split_text(text)
            logger.info(f"Created {len(chunks)} chunks from {pdf_path}")
        else:
            chunks = []
            logger.warning(f"No text extracted from {pdf_path}")

        # Step 4: Create metadata for each chunk
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()
            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "ocr_processed": ocr_used,
                    "ocr_quality": ocr_quality,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
            "ocr_used": ocr_used,
            "ocr_quality": ocr_quality,
        }

    def _extract_text_from_pdf(self, reader: Any) -> str:
        """
        Extract text from PDF using pypdf.

        Args:
            reader: PdfReader instance

        Returns:
            Extracted text
        """
        text_parts = []
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if text:
                    text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
            except Exception as e:
                logger.warning(f"Error extracting text from page {page_num + 1}: {e}")

        return "\n\n".join(text_parts)

    def _extract_text_via_ocr(self, pdf_path: Path) -> str:
        """
        Extract text from PDF using OCR (Tesseract).

        Converts PDF pages to images and applies OCR.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text
        """
        if not pytesseract or not Image:
            logger.error("pytesseract or Pillow not available for OCR")
            return ""

        try:
            from pdf2image import convert_from_path
        except ImportError:
            logger.error("pdf2image not installed, cannot perform OCR")
            return ""

        text_parts = []
        try:
            # Convert PDF pages to images
            images = convert_from_path(str(pdf_path))
            logger.info(f"Converted {len(images)} pages for OCR")

            for page_num, image in enumerate(images):
                try:
                    # Run OCR with French and English
                    text = pytesseract.image_to_string(
                        image,
                        lang="fra+eng",
                        config="--psm 1 --oem 3",
                    )
                    if text.strip():
                        text_parts.append(f"--- Page {page_num + 1} (OCR) ---\n{text}")
                except Exception as e:
                    logger.warning(f"OCR failed on page {page_num + 1}: {e}")

        except Exception as e:
            logger.error(f"Error converting PDF to images for OCR: {e}")

        return "\n\n".join(text_parts)

    @staticmethod
    def _assess_ocr_quality(text: str) -> str:
        """
        Assess the quality of OCR extraction.

        Simple heuristic based on:
        - Text length
        - Average word length
        - Special character ratio

        Args:
            text: Extracted text

        Returns:
            "high", "low", or "medium"
        """
        if not text.strip():
            return "low"

        words = text.split()
        if not words:
            return "low"

        avg_word_length = sum(len(w) for w in words) / len(words)

        # High quality: decent length, reasonable word lengths, low garbling
        if len(text) > 1000 and 3 < avg_word_length < 15:
            return "high"

        # Low quality: very short, very long words (garbling), or mostly special chars
        special_char_ratio = sum(1 for c in text if not c.isalnum() and c != " ") / len(
            text
        )
        if special_char_ratio > 0.5:
            return "low"

        return "high" if len(text) > 500 else "low"

    @staticmethod
    def _compute_hash(text: str) -> str:
        """
        Compute SHA-256 hash of text content.

        Args:
            text: Text content

        Returns:
            First 12 characters of SHA-256 hash
        """
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_pdf_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[dict[str, Any]]:
    """
    Load all PDFs from a directory.

    Args:
        directory: Path to directory containing PDFs
        chunk_size: Chunk size for splitting
        chunk_overlap: Chunk overlap for splitting

    Returns:
        List of document dictionaries with chunks and metadatas
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    loader = PDFLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for pdf_file in directory.glob("*.pdf"):
        try:
            logger.info(f"Processing {pdf_file.name}...")
            result = loader.load_and_chunk(pdf_file)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {pdf_file}: {e}")

    logger.info(f"Loaded {len(documents)} PDF documents from {directory}")
    return documents
