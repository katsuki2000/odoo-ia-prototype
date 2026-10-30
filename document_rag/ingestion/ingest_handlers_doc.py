"""Load supported documents and add their chunks to the documentary collection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

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
    pdf_loader_cls: type = PDFLoader,
    wiki_loader_cls: type = WikiLoader,
) -> None:
    """Ingest supported files recursively, recording failures per file."""
    if not docs_dir.is_dir():
        logger.warning("Docs directory not found: %s", docs_dir)
        return

    pdf_loader = pdf_loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    wiki_loader = wiki_loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    stats.setdefault("total_chunks", 0)
    stats.setdefault("by_source", {})
    stats.setdefault("by_type", {})
    stats.setdefault("load_times", {})

    for path in sorted(file for file in docs_dir.rglob("*") if file.is_file() and is_supported_document(file)):
        try:
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                result = pdf_loader.load_and_chunk(path, scan_root=docs_dir)
            else:
                loader = {
                    ".txt": wiki_loader.load_text_file,
                    ".md": wiki_loader.load_markdown_file,
                    ".docx": wiki_loader.load_docx_file,
                }[suffix]
                result = loader(path, scan_root=docs_dir)

            chunks, metadatas = result["chunks"], result["metadatas"]
            if not chunks:
                logger.warning("No chunks extracted from %s", path)
                continue

            ids = docs_manager.add_chunks(chunks, metadatas)
            source = path.relative_to(docs_dir).as_posix()
            doc_type = metadatas[0].get("type", "document")
            stats["total_chunks"] += len(ids)
            stats["by_source"][source] = len(ids)
            stats["by_type"][doc_type] = stats["by_type"].get(doc_type, 0) + len(ids)
            logger.info("Indexed %s (%d chunks)", source, len(ids))
        except Exception:
            logger.exception("Failed to ingest %s", path)
