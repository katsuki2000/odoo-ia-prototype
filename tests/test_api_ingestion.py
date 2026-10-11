"""Tests for Step 5b Day 2 ingestion API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from api.schemas import ReindexRequestV1
from api.routes_ingestion import ingestion_status, reindex_v1
from config.settings import DOCS_COLLECTION_NAME
from document_rag.vectorstore.chroma_manager import ChromaManager


def test_api_v1_incremental_reindex_indexes_requested_path(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    source_file = docs_dir / "api_doc.txt"
    source_file.write_text("API ingestion document.", encoding="utf-8")
    manager = MagicMock()
    manager.get_stats.return_value = {"total_chunks": 1}
    manager.db_path = tmp_path / "chroma"
    manager.collection_name = "api_incremental"

    with (
        patch("api.main.ChromaManager", return_value=manager),
        patch("api.main.reindex_if_changed") as reindex,
        patch("api.main.write_ingestion_event"),
        patch("api.routes_ingestion.confine_to_scan_roots", return_value=docs_dir.resolve()),
    ):
        reindex.return_value = {
            "added_files": [str(source_file.resolve())],
            "updated_files": [],
            "deleted_files": [],
            "skipped_files": [],
            "failed_files": {},
            "chunks_added": 1,
            "chunks_deleted": 0,
        }
        response = reindex_v1(ReindexRequestV1(scope="incremental", path=str(docs_dir)))

    payload = response.model_dump()
    assert payload["status"] == "success"
    assert payload["scope"] == "incremental"
    assert str(source_file.resolve()) in payload["result"]["added_files"]
    assert payload["total_chunks"] == 1


def test_api_v1_reindex_rejects_path_outside_scan_roots(tmp_path):
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / "passwd.txt").write_text("leak", encoding="utf-8")
    manager = MagicMock()

    with (
        patch("api.main.ChromaManager", return_value=manager),
        patch("api.main.reindex_if_changed") as reindex,
        patch("api.main.write_ingestion_event"),
    ):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            reindex_v1(ReindexRequestV1(scope="incremental", path=str(outside)))

    assert exc_info.value.status_code == 400
    assert "outside configured ingestion roots" in str(exc_info.value.detail)
    reindex.assert_not_called()


def test_api_v1_ingestion_status_reports_stats_and_watcher_state(tmp_path):
    manager = MagicMock()
    manager.get_stats.return_value = {"total_chunks": 1}

    with patch("api.main.ChromaManager", return_value=manager):
        response = ingestion_status()

    payload = response.model_dump()
    assert payload["total_chunks"] == 1
    assert payload["files_monitored"] >= 0
    assert payload["watcher_status"]["watcher_running"] is False


def test_api_v1_reindex_rejects_invalid_scope():
    with pytest.raises(ValidationError):
        ReindexRequestV1(scope="unknown")


def test_api_status_reads_the_collection_the_retrieval_uses(tmp_path):
    stored = ChromaManager(db_path=tmp_path, collection_name=DOCS_COLLECTION_NAME)
    stored.collection.add(
        ids=["chunk-1"], documents=["text"], embeddings=[[0.1] * 384], metadatas=[{"source": "doc.txt"}],
    )

    with patch("document_rag.vectorstore.chroma_manager.CHROMA_PATH", tmp_path):
        response = ingestion_status()

    assert response.total_chunks == 1
