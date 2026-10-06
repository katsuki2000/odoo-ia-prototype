"""
document_rag/ingestion/ingest_handlers_doc.py

Document-type ingestion handlers for PDF and Wiki/Markdown files.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
import time
from typing import Any, Optional

from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.pdf_loader import PDFLoader
from document_rag.ingestion.wiki_loader import WikiLoader

logger = logging.getLogger(__name__)


def load_and_ingest_pdfs(
    loader_cls: Any,
    docs_manager: Any,
    stats: dict[str, Any],
    docs_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    scan_root: Optional[Path] = None,
) -> None:
    """Load and ingest PDF documents."""
    loader = loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    for pdf_file in docs_dir.glob("*.pdf"):
        try:
            logger.info(f"  Processing: {pdf_file.name}")
            result = loader.load_and_chunk(pdf_file, scan_root=scan_root)

            chunks = result["chunks"]
            metadatas = result["metadatas"]
            ocr_used = result["ocr_used"]

            if chunks:
                ids = docs_manager.add_chunks(chunks, metadatas)
                logger.info(f"    Added {len(ids)} chunks (OCR: {ocr_used})")

                stats["total_chunks"] += len(chunks)
                stats["by_source"][pdf_file.name] = len(chunks)
                stats["by_type"]["doc_pdf"] = (
                    stats["by_type"].get("doc_pdf", 0) + len(chunks)
                )
            else:
                logger.warning(f"    No chunks extracted from {pdf_file.name}")

        except Exception as e:
            logger.error(f"  Error processing {pdf_file.name}: {e}")


def load_and_ingest_wiki(
    loader_cls: Any,
    docs_manager: Any,
    stats: dict[str, Any],
    docs_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    scan_root: Optional[Path] = None,
) -> None:
    """Load and ingest wiki/markdown documents."""
    loader = loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    loaders = (
        ("*.txt", lambda path: loader.load_text_file(path, scan_root=scan_root)),
        ("*.md", lambda path: loader.load_markdown_file(path, scan_root=scan_root)),
        ("*.docx", lambda path: loader.load_docx_file(path, scan_root=scan_root)),
    )
    for pattern, load_file in loaders:
        for doc_file in sorted(docs_dir.glob(pattern)):
            if not is_supported_document(doc_file):
                continue
            _ingest_wiki_file(doc_file, load_file, docs_manager, stats)


def _ingest_wiki_file(doc_file: Path, load_file: Any, docs_manager: Any, stats: dict[str, Any]) -> None:
    try:
        logger.info(f"  Processing: {doc_file.name}")
        result = load_file(doc_file)

        chunks = result["chunks"]
        metadatas = result["metadatas"]

        if chunks:
            ids = docs_manager.add_chunks(chunks, metadatas)
            logger.info(f"    Added {len(ids)} chunks")

            stats["total_chunks"] += len(chunks)
            stats["by_source"][doc_file.name] = len(chunks)
            stats["by_type"]["doc_wiki"] = (
                stats["by_type"].get("doc_wiki", 0) + len(chunks)
            )

    except Exception as e:
        logger.error(f"  Error processing {doc_file.name}: {e}")


def ingest_documents_dir(
    docs_dir: Path,
    docs_manager: Any,
    stats: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Ingest PDF, markdown, and text files from a documents directory."""
    if not docs_dir.exists():
        logger.warning(f"Docs directory not found: {docs_dir}")
        return

    target_mod = sys.modules.get("document_rag.ingestion.ingest_all")
    pdf_loader_cls = getattr(target_mod, "PDFLoader", PDFLoader) if target_mod else PDFLoader
    wiki_loader_cls = getattr(target_mod, "WikiLoader", WikiLoader) if target_mod else WikiLoader

    pdf_files = list(docs_dir.glob("*.pdf"))
    if pdf_files:
        logger.info(f"Found {len(pdf_files)} PDF files")
        start = time.time()
        try:
            load_and_ingest_pdfs(
                pdf_loader_cls, docs_manager, stats, docs_dir, chunk_size, chunk_overlap, scan_root=docs_dir
            )
        except Exception as e:
            logger.error(f"Error loading PDFs: {e}")
        elapsed = time.time() - start
        stats["load_times"]["pdfs"] = elapsed
        logger.info(f"PDF ingestion took {elapsed:.2f}s")

    txt_files = list(docs_dir.glob("*.txt"))
    md_files = list(docs_dir.glob("*.md"))
    docx_files = [path for path in docs_dir.glob("*.docx") if is_supported_document(path)]
    if txt_files or md_files or docx_files:
        logger.info(f"Found {len(txt_files)} .txt, {len(md_files)} .md and {len(docx_files)} .docx files")
        start = time.time()
        try:
            load_and_ingest_wiki(
                wiki_loader_cls, docs_manager, stats, docs_dir, chunk_size, chunk_overlap, scan_root=docs_dir
            )
        except Exception as e:
            logger.error(f"Error loading wiki files: {e}")
        elapsed = time.time() - start
        stats["load_times"]["wiki"] = elapsed
        logger.info(f"Wiki ingestion took {elapsed:.2f}s")
