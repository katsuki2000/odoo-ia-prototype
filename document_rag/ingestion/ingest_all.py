"""Orchestrate full ingestion of the configured documentary corpus."""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import Any

from config.settings import DOCS_COLLECTION_NAME, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.ingestion.ingest_handlers_doc import ingest_documents_dir
from document_rag.ingestion.pdf_loader import PDFLoader
from document_rag.ingestion.scan_root import DOCS_DIR
from document_rag.ingestion.wiki_loader import WikiLoader
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """Coordinate document loading and ChromaDB indexing."""

    def __init__(
        self,
        chroma_db_path: str | Path | None = None,
        collection_name: str = DOCS_COLLECTION_NAME,
        chunk_size: int = RAG_CHUNK_SIZE,
        chunk_overlap: int = RAG_CHUNK_OVERLAP,
    ):
        if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("Chunk overlap must be non-negative and smaller than chunk size.")
        self.docs_manager = ChromaManager(db_path=chroma_db_path, collection_name=collection_name)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.stats: dict[str, Any] = {
            "total_chunks": 0,
            "by_type": {},
            "by_source": {},
            "by_module": {},
            "load_times": {},
        }
        self.last_docs_dir: str | Path = DOCS_DIR

    def ingest_all(self, docs_dir: str | Path = DOCS_DIR) -> dict[str, Any]:
        """Index every supported document below docs_dir."""
        self.last_docs_dir = docs_dir
        docs_path = Path(docs_dir) if str(docs_dir) else None
        if docs_path is not None and docs_path.is_dir():
            self._ingest_documents_dir(docs_path)
        elif docs_path is not None:
            logger.warning("Docs directory not found: %s", docs_path)

        stats = self.docs_manager.get_stats()
        result = {
            "total_chunks": stats.get("total_chunks", 0),
            "by_type": dict(stats.get("by_type", {})),
            "by_module": dict(stats.get("by_module", {})),
        }
        logger.info("Ingestion complete: %d chunks", result["total_chunks"])
        return result

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
        """Replace the collection contents with a fresh ingestion."""
        self.docs_manager.delete_collection()
        return self.ingest_all(docs_dir if docs_dir is not None else self.last_docs_dir)


from document_rag.ingestion.ingest_cli import main


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["IngestionOrchestrator", "main"]
