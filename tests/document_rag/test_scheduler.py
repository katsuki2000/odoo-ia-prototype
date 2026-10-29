"""Incremental scan of the documents folder: startup, periodic loop and the manual trigger."""

from threading import Event
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.main import app
from document_rag.ingestion.scheduler import PERIODIC_SCAN, STARTUP_SCAN, run_scan, start_scan_loop

SCAN_RESULT = {
    "added_files": ["doc.txt"],
    "updated_files": [],
    "deleted_files": [],
    "skipped_files": [],
    "failed_files": {},
    "chunks_added": 1,
    "chunks_deleted": 0,
}


@pytest.fixture
def test_client():
    app.dependency_overrides[require_admin] = lambda: {"uid": 1, "is_admin": True}
    yield TestClient(app)
    app.dependency_overrides.pop(require_admin, None)


@pytest.mark.parametrize("scan_type", [STARTUP_SCAN, PERIODIC_SCAN])
def test_run_scan_updates_status_and_logs_event(tmp_path, scan_type):
    status_dict = {"last_ingestion_time": None, "last_result": None, "last_scan_type": None}

    with (
        patch("document_rag.ingestion.scheduler.reindex_if_changed", return_value=SCAN_RESULT) as mock_reindex,
        patch("document_rag.ingestion.scheduler.write_ingestion_event") as mock_write,
    ):
        result = run_scan(scan_type, [tmp_path], docs_manager=MagicMock(), status_dict=status_dict)

    assert result == SCAN_RESULT
    assert mock_reindex.call_args.args[0] == [tmp_path]
    assert status_dict["last_scan_type"] == scan_type
    assert status_dict["last_result"] == SCAN_RESULT
    assert status_dict["last_ingestion_time"] is not None
    mock_write.assert_called_once_with(
        event_type=scan_type,
        result=result,
        started_at=pytest.approx(mock_write.call_args.kwargs["started_at"], abs=10),
    )


def test_scan_loop_scans_at_startup_then_periodically():
    scan_types = []
    second_scan_done = Event()

    def record(scan_type, roots, status_dict):
        scan_types.append(scan_type)
        if len(scan_types) == 2:
            second_scan_done.set()
        return SCAN_RESULT

    with patch("document_rag.ingestion.scheduler.run_scan", side_effect=record):
        stop_event = start_scan_loop(interval_hours=0.00001, status_dict={})
        assert second_scan_done.wait(timeout=5)
        stop_event.set()

    assert scan_types[:2] == [STARTUP_SCAN, PERIODIC_SCAN]


def test_api_trigger_scheduled_scan_endpoint(test_client):
    manager = MagicMock()
    manager.get_stats.return_value = {"total_chunks": 10}

    with (
        patch("api.routes_ingestion.ChromaManager", return_value=manager),
        patch("api.routes_ingestion.run_scan", return_value={**SCAN_RESULT, "chunks_added": 5}),
    ):
        response = test_client.post("/api/v1/ingestion/scheduled-scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["scan_type"] == PERIODIC_SCAN
    assert payload["result"]["chunks_added"] == 5


def test_api_ingestion_status_includes_scheduler_info(test_client):
    manager = MagicMock()
    manager.get_stats.return_value = {"total_chunks": 42}

    with patch("api.routes_ingestion.ChromaManager", return_value=manager):
        response = test_client.get("/api/v1/ingestion/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_chunks"] == 42
    assert set(payload["scheduler_status"]) == {"interval_hours", "running"}
    assert "last_scan_type" in payload
