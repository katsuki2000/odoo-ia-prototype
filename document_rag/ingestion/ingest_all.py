"""Orchestrate full document ingestion into ChromaDB."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config.settings import DOCS_COLLECTION_NAME, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.ingestion.ingest_handlers_doc import ingest_documents_dir
from document_rag.ingestion.logging_utils import LOGS_DIR
from document_rag.ingestion.pdf_loader import PDFLoader, load_pdf_directory
from document_rag.ingestion.scan_root import DOCS_DIR, resolve_scan_root
from document_rag.ingestion.wiki_loader import WikiLoader, load_wiki_directory
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """Coordinate a full local-document ingestion run."""

    def __init__(
        self,
        chroma_db_path: str | Path | None = None,
        collection_name: str = DOCS_COLLECTION_NAME,
        chunk_size: int = RAG_CHUNK_SIZE,
        chunk_overlap: int = RAG_CHUNK_OVERLAP,
    ):
        self.docs_manager = ChromaManager(db_path=chroma_db_path, collection_name=collection_name)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.stats = {
            "total_chunks": 0,
            "by_type": {},
            "by_source": {},
            "by_module": {},
            "load_times": {},
        }
        self.last_docs_dir: str | Path = DOCS_DIR

    def ingest_all(self, docs_dir: str | Path = DOCS_DIR) -> dict[str, Any]:
        """Index all supported documents directly under docs_dir."""
        docs_dir_path = Path(docs_dir) if str(docs_dir) else None
        self.last_docs_dir = docs_dir
        logger.info("Starting document ingestion from %s", docs_dir)

        if docs_dir_path is None:
            logger.info("Document ingestion skipped: no directory configured.")
        elif docs_dir_path.is_dir():
            self._ingest_documents_dir(docs_dir_path)
        else:
            logger.warning("Document directory not found: %s", docs_dir)

        manager_stats = self.docs_manager.get_stats()
        final_stats = {
            "total_chunks": manager_stats.get("total_chunks", 0),
            "by_type": dict(manager_stats.get("by_type", {})),
            "by_module": dict(manager_stats.get("by_module", {})),
        }
        logger.info(
            "Document ingestion complete: %d chunks; types=%s; modules=%s",
            final_stats["total_chunks"],
            final_stats["by_type"],
            final_stats["by_module"],
        )
        return final_stats

    def _ingest_documents_dir(self, docs_dir: Path) -> None:
        ingest_documents_dir(
            docs_dir,
            self.docs_manager,
            self.stats,
            self.chunk_size,
            self.chunk_overlap,
            pdf_loader_cls=PDFLoader,
            wiki_loader_cls=WikiLoader,
        )

    def clear_and_reingest(self, docs_dir: str | Path | None = None) -> dict[str, Any]:
        """Replace collection contents with the documents currently in docs_dir."""
        target_docs_dir = docs_dir if docs_dir is not None else self.last_docs_dir
        logger.info("Clearing document collection before full ingestion.")
        self.docs_manager.delete_collection()
        return self.ingest_all(docs_dir=target_docs_dir)


from document_rag.ingestion.ingest_cli import main


if __name__ == "__main__":
    import sys
    sys.exit(main())


__all__ = [
    "IngestionOrchestrator",
    "main",
    "DOCS_DIR",
    "LOGS_DIR",
    "PDFLoader",
    "WikiLoader",
    "ChromaManager",
    "load_pdf_directory",
    "load_wiki_directory",
    "resolve_scan_root",
]
