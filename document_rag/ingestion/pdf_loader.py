"""
PDF document loader with OCR support for scanned PDFs.

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
except ImportError:
    Image = None

from langchain_text_splitters import RecursiveCharacterTextSplitter

from document_rag.ingestion.scan_root import compute_source
from document_rag.ingestion.pdf_ocr import extract_text_via_ocr, assess_ocr_quality

logger = logging.getLogger(__name__)


class PDFLoader:
    """Loads and processes PDF documents with automatic OCR detection."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        ocr_threshold: float = 0.1,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.ocr_threshold = ocr_threshold

        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

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
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        if not PdfReader:
            raise ImportError("pypdf is required for PDF loading")

        base_metadata = metadata or {}
        base_metadata.setdefault("source", compute_source(pdf_path, scan_root))
        base_metadata.setdefault("type", "doc_pdf")
        base_metadata["file_size"] = pdf_path.stat().st_size

        logger.info("Loading PDF: %s", pdf_path)
        try:
            reader = PdfReader(str(pdf_path))
            text = self._extract_text_from_pdf(reader)
            ocr_used = False
            ocr_quality = None
        except Exception as e:
            logger.warning("Error extracting text from %s: %s", pdf_path, e)
            text = ""
            ocr_used = False
            ocr_quality = None

        pdf_size = base_metadata.get("file_size", 1)
        text_extracted_ratio = len(text) / pdf_size if pdf_size > 0 else 0

        if text_extracted_ratio < self.ocr_threshold:
            logger.info("Low text extraction ratio (%.2f%%), attempting OCR", text_extracted_ratio * 100)
            if pytesseract and Image:
                ocr_text = self._extract_text_via_ocr(pdf_path)
                if ocr_text and len(ocr_text) > len(text):
                    text = ocr_text
                    ocr_used = True
                    ocr_quality = self._assess_ocr_quality(text)
                    logger.info("OCR extraction complete. Quality: %s", ocr_quality)
            else:
                logger.warning("pytesseract or Pillow not installed, skipping OCR")

        chunks = self.splitter.split_text(text) if text.strip() else []
        if not chunks:
            logger.warning("No text extracted from %s", pdf_path)

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
        text_parts = []
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if text:
                    text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
            except Exception as e:
                logger.warning("Error extracting text from page %d: %s", page_num + 1, e)
        return "\n\n".join(text_parts)

    def _extract_text_via_ocr(self, pdf_path: Path) -> str:
        return extract_text_via_ocr(pdf_path)

    @staticmethod
    def _assess_ocr_quality(text: str) -> str:
        return assess_ocr_quality(text)

    @staticmethod
    def _compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_pdf_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    scan_root: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    root = Path(scan_root) if scan_root is not None else directory
    loader = PDFLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for pdf_file in directory.glob("*.pdf"):
        try:
            logger.info("Processing %s...", pdf_file.name)
            result = loader.load_and_chunk(pdf_file, scan_root=root)
            documents.append(result)
        except Exception as e:
            logger.error("Error processing %s: %s", pdf_file, e)

    logger.info("Loaded %d PDF documents from %s", len(documents), directory)
    return documents
