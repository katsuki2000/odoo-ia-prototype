"""
document_rag/ingestion/ingest_all.py

Master ingestion orchestrator for all document types.
Facade module combining configuration, loaders, and orchestrator execution.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import Any, Optional

from document_rag.ingestion.ingest_config import (
    CORE_MODULES_ALWAYS_LOADED,
    DOCS_DIR,
    LOGS_DIR,
    PROJECT_ROOT,
    setup_ingestion_logging,
)
from document_rag.ingestion.ingest_handlers_doc import (
    ingest_documents_dir,
    load_and_ingest_pdfs,
    load_and_ingest_wiki,
)
from document_rag.ingestion.pdf_loader import PDFLoader, load_pdf_directory
from document_rag.ingestion.scan_root import resolve_scan_root
from document_rag.ingestion.wiki_loader import WikiLoader, load_wiki_directory
from document_rag.vectorstore.chroma_manager import ChromaManager
from config.settings import DOCS_COLLECTION_NAME, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """Orchestrates multi-source document ingestion to ChromaDB."""

    def __init__(
        self,
        chroma_db_path: str | Path = "vectorstore/chroma_db",
        collection_name: str = DOCS_COLLECTION_NAME,
        chunk_size: int = RAG_CHUNK_SIZE,
        chunk_overlap: int = RAG_CHUNK_OVERLAP,
    ):
        self.docs_manager = ChromaManager(
            db_path=chroma_db_path,
            collection_name=collection_name,
        )
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
        self.last_incremental: bool = False

    def ingest_all(
        self,
        docs_dir: str | Path = DOCS_DIR,
        incremental: bool = False,
    ) -> dict[str, Any]:
        """Ingest all documents from docs directory."""
        docs_dir_path = Path(docs_dir) if str(docs_dir) != "" else None

        self.last_docs_dir = docs_dir
        self.last_incremental = incremental

        logger.info("=" * 60)
        logger.info("Starting full document ingestion")
        logger.info("=" * 60)

        if docs_dir_path and docs_dir_path.exists():
            logger.info(f"\n[DOCS] Loading from {docs_dir_path}")
            self._ingest_documents_dir(docs_dir_path)
        else:
            logger.warning(f"Docs directory not found or empty: {docs_dir}")

        docs_stats = self.docs_manager.get_stats()

        final_stats = {
            "total_chunks": docs_stats.get("total_chunks", 0),
            "by_type": dict(docs_stats.get("by_type", {})),
            "by_module": dict(docs_stats.get("by_module", {})),
        }
        logger.info("\n" + "=" * 60)
        logger.info("INGESTION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total chunks indexed: {final_stats['total_chunks']}")
        logger.info(f"By type: {final_stats['by_type']}")
        logger.info(f"By module: {final_stats['by_module']}")

        return final_stats

    def _ingest_documents_dir(self, docs_dir: Path) -> None:
        """Ingest PDF, markdown, and text files."""
        ingest_documents_dir(docs_dir, self.docs_manager, self.stats, self.chunk_size, self.chunk_overlap)

    def _load_and_ingest_pdfs(self, docs_dir: Path, scan_root: Optional[Path] = None) -> None:
        target_mod = sys.modules.get("document_rag.ingestion.ingest_all")
        loader_cls = getattr(target_mod, "PDFLoader", PDFLoader) if target_mod else PDFLoader
        load_and_ingest_pdfs(loader_cls, self.docs_manager, self.stats, docs_dir, self.chunk_size, self.chunk_overlap, scan_root)

    def _load_and_ingest_wiki(self, docs_dir: Path, scan_root: Optional[Path] = None) -> None:
        target_mod = sys.modules.get("document_rag.ingestion.ingest_all")
        loader_cls = getattr(target_mod, "WikiLoader", WikiLoader) if target_mod else WikiLoader
        load_and_ingest_wiki(loader_cls, self.docs_manager, self.stats, docs_dir, self.chunk_size, self.chunk_overlap, scan_root)

    def clear_and_reingest(
        self,
        docs_dir: Optional[str | Path] = None,
        incremental: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Clear collection and re-ingest all documents."""
        logger.info("Clearing collection...")
        self.docs_manager.delete_collection()
        logger.info("Collection cleared.")

        target_docs = docs_dir if docs_dir is not None else getattr(self, "last_docs_dir", DOCS_DIR)
        target_inc = incremental if incremental is not None else getattr(self, "last_incremental", False)

        return self.ingest_all(
            docs_dir=target_docs,
            incremental=target_inc,
        )


from document_rag.ingestion.ingest_cli import main


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "IngestionOrchestrator",
    "main",
    "DOCS_DIR",
    "LOGS_DIR",
    "CORE_MODULES_ALWAYS_LOADED",
    "PROJECT_ROOT",
    "PDFLoader",
    "WikiLoader",
    "ChromaManager",
    "load_pdf_directory",
    "load_wiki_directory",
    "resolve_scan_root",
    "setup_ingestion_logging",
]
