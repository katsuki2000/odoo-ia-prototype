"""Ingest supported local documents into the documentation collection."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any

from document_rag.ingestion.document_loader import load_document
from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.pdf_loader import PDFLoader
from document_rag.ingestion.wiki_loader import WikiLoader

logger = logging.getLogger(__name__)


def ingest_documents_dir(
    docs_dir: Path,
    docs_manager: Any,
    stats: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    pdf_loader_cls: type[PDFLoader] = PDFLoader,
    wiki_loader_cls: type[WikiLoader] = WikiLoader,
) -> None:
    """Index supported files directly under a document directory."""
    if not docs_dir.is_dir():
        logger.warning("Document directory not found: %s", docs_dir)
        return

    files = sorted(
        path for path in docs_dir.iterdir()
        if path.is_file() and is_supported_document(path)
    )
    pdf_files = [path for path in files if path.suffix.lower() == ".pdf"]
    wiki_files = [path for path in files if path.suffix.lower() in {".txt", ".md", ".docx"}]

    loader_groups = (
        ("pdfs", pdf_files, pdf_loader_cls),
        ("wiki", wiki_files, wiki_loader_cls),
    )
    for group, selected_files, loader_cls in loader_groups:
        if not selected_files:
            continue

        started_at = time.perf_counter()
        try:
            loader = loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        except Exception:
            logger.exception("Could not initialize %s document loader.", group)
            stats.setdefault("load_times", {})[group] = time.perf_counter() - started_at
            continue

        for file_path in selected_files:
            _ingest_file(
                file_path,
                docs_dir,
                docs_manager,
                stats,
                chunk_size,
                chunk_overlap,
                loader if group == "pdfs" else None,
                loader if group == "wiki" else None,
            )
        stats.setdefault("load_times", {})[group] = time.perf_counter() - started_at


def _ingest_file(
    file_path: Path,
    scan_root: Path,
    docs_manager: Any,
    stats: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    pdf_loader: PDFLoader | None,
    wiki_loader: WikiLoader | None,
) -> None:
    try:
        logger.info("Processing document: %s", file_path.name)
        chunks, metadatas = load_document(
            file_path,
            chunk_size,
            chunk_overlap,
            scan_root,
            pdf_loader=pdf_loader,
            wiki_loader=wiki_loader,
        )
        if not chunks:
            logger.warning("No text extracted from %s", file_path.name)
            return

        added_ids = docs_manager.add_chunks(chunks, metadatas)
        added_count = len(added_ids)
        doc_type = "doc_pdf" if file_path.suffix.lower() == ".pdf" else "doc_wiki"
        stats["total_chunks"] = stats.get("total_chunks", 0) + added_count
        stats.setdefault("by_source", {})[file_path.name] = added_count
        by_type = stats.setdefault("by_type", {})
        by_type[doc_type] = by_type.get(doc_type, 0) + added_count
        logger.info("Added %d chunks from %s", added_count, file_path.name)
    except Exception:
        logger.exception("Failed to ingest document: %s", file_path.name)
