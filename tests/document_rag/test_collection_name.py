"""Regression: every documentary component targets the single collection DOCS_COLLECTION_NAME."""

from pathlib import Path
from unittest.mock import patch

import chromadb

from config.settings import DOCS_COLLECTION_NAME
from document_rag.ingestion.ingest_all import IngestionOrchestrator
from document_rag.ingestion.scheduler import PERIODIC_SCAN, STARTUP_SCAN, run_scan
from document_rag.vectorstore.chroma_manager import ChromaManager


def _collection_names(db_path: Path) -> set[str]:
    client = chromadb.PersistentClient(path=str(db_path))
    return {getattr(collection, "name", collection) for collection in client.list_collections()}


def test_chroma_manager_defaults_to_the_documentary_collection(tmp_path):
    manager = ChromaManager(db_path=tmp_path)
    assert manager.collection_name == DOCS_COLLECTION_NAME
    assert _collection_names(tmp_path) == {DOCS_COLLECTION_NAME}


def test_orchestrator_defaults_to_the_documentary_collection(tmp_path):
    orchestrator = IngestionOrchestrator(chroma_db_path=tmp_path)
    assert orchestrator.docs_manager.collection_name == DOCS_COLLECTION_NAME
    assert _collection_names(tmp_path) == {DOCS_COLLECTION_NAME}


def test_orchestrator_honors_its_collection_name(tmp_path):
    orchestrator = IngestionOrchestrator(chroma_db_path=tmp_path, collection_name="custom")
    assert orchestrator.docs_manager.collection_name == "custom"
    assert _collection_names(tmp_path) == {"custom"}


def test_pipeline_components_only_create_the_documentary_collection(tmp_path):
    db_path = tmp_path / "chroma_db"
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    with (
        patch("document_rag.vectorstore.chroma_manager.CHROMA_PATH", db_path),
        patch("document_rag.ingestion.scheduler.write_ingestion_event"),
    ):
        IngestionOrchestrator(chroma_db_path=db_path)
        run_scan(STARTUP_SCAN, [docs_dir])
        run_scan(PERIODIC_SCAN, [docs_dir])

    assert _collection_names(db_path) == {DOCS_COLLECTION_NAME}
