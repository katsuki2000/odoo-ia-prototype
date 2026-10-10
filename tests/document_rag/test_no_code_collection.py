"""Regression: the documentary pipeline must never create an `odoo_code` collection."""

from pathlib import Path
from unittest.mock import patch

import chromadb

from document_rag.ingestion.ingest_all import IngestionOrchestrator
from document_rag.ingestion.scheduler import (
    PeriodicScanScheduler,
    run_scheduled_scan,
    run_startup_scan,
)
from document_rag.ingestion.watcher import IngestionWatcher


def _collection_names(db_path: Path) -> set[str]:
    client = chromadb.PersistentClient(path=str(db_path))
    return {getattr(collection, "name", collection) for collection in client.list_collections()}


def test_odoo_code_collection_is_never_created(tmp_path):
    db_path = tmp_path / "chroma_db"
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    with (
        patch("document_rag.vectorstore.chroma_manager.CHROMA_PATH", db_path),
        patch("document_rag.ingestion.scheduler.write_ingestion_event"),
    ):
        IngestionOrchestrator(chroma_db_path=db_path)
        IngestionWatcher(watched_paths=[docs_dir])
        PeriodicScanScheduler(roots=[docs_dir])
        run_startup_scan([docs_dir])
        run_scheduled_scan([docs_dir])

    assert "odoo_code" not in _collection_names(db_path)
