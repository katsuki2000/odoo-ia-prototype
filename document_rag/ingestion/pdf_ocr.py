"""
OCR utilities for PDF documents using pytesseract and pdf2image.
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger(__name__)


def extract_text_via_ocr(pdf_path: Path) -> str:
    """Extract text from PDF pages via OCR (Tesseract)."""
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
        images = convert_from_path(str(pdf_path))
        logger.info("Converted %d pages for OCR", len(images))

        for page_num, image in enumerate(images):
            try:
                text = pytesseract.image_to_string(
                    image,
                    lang="fra+eng",
                    config="--psm 1 --oem 3",
                )
                if text.strip():
                    text_parts.append(f"--- Page {page_num + 1} (OCR) ---\n{text}")
            except Exception as e:
                logger.warning("OCR failed on page %d: %s", page_num + 1, e)
    except Exception as e:
        logger.error("Error converting PDF to images for OCR: %s", e)

    return "\n\n".join(text_parts)


def assess_ocr_quality(text: str) -> str:
    """Assess quality of OCR extraction (high or low)."""
    if not text.strip():
        return "low"

    words = text.split()
    if not words:
        return "low"

    avg_word_length = sum(len(w) for w in words) / len(words)
    if len(text) > 1000 and 3 < avg_word_length < 15:
        return "high"

    special_char_ratio = sum(1 for c in text if not c.isalnum() and c != " ") / len(text)
    if special_char_ratio > 0.5:
        return "low"

    return "high" if len(text) > 500 else "low"
