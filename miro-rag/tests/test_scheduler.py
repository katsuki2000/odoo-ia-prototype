"""
Tests for Step 5b Day 3: Scheduled Full Scan & Startup Behavior.
"""

from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app, LAST_INGESTION_STATUS
from ingestion.scheduler import PeriodicScanScheduler, run_scheduled_scan, run_startup_scan


@pytest.fixture
def test_client():
    return TestClient(app)


def test_run_startup_scan_updates_status_and_logs_event(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "startup_doc.txt").write_text("Created while offline.", encoding="utf-8")
    
    manager = MagicMock()
    status_dict = {
        "last_ingestion_time": None,
        "last_result": None,
        "last_scan_type": None,
        "scheduler_status": {"running": False, "interval_hours": 6},
    }

    with (
        patch("ingestion.scheduler.reindex_if_changed") as mock_reindex,
        patch("ingestion.scheduler.write_ingestion_event") as mock_write,
    ):
        mock_reindex.return_value = {
            "added_files": [str(docs_dir / "startup_doc.txt")],
            "updated_files": [],
            "deleted_files": [],
            "skipped_files": [],
            "failed_files": {},
            "chunks_added": 1,
            "chunks_deleted": 0,
        }
        
        result = run_startup_scan([docs_dir], docs_manager=manager, code_manager=manager, status_dict=status_dict)

    assert result["chunks_added"] == 1
    assert status_dict["last_scan_type"] == "startup_incremental_scan"
    assert status_dict["last_ingestion_time"] is not None
    assert mock_write.call_count == 1
    mock_write.assert_called_once_with(
        event_type="startup_incremental_scan",
        result=result,
        started_at=pytest.approx(mock_write.call_args.kwargs["started_at"], abs=10),
    )


def test_run_scheduled_scan_updates_status_and_logs_event(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    
    manager = MagicMock()
    status_dict = {
        "last_ingestion_time": None,
        "last_result": None,
        "last_scan_type": None,
        "scheduler_status": {"running": True, "interval_hours": 6},
    }

    with (
        patch("ingestion.scheduler.reindex_if_changed") as mock_reindex,
        patch("ingestion.scheduler.write_ingestion_event") as mock_write,
    ):
        mock_reindex.return_value = {
            "added_files": [],
            "updated_files": [str(docs_dir / "edited.txt")],
            "deleted_files": [],
            "skipped_files": [],
            "failed_files": {},
            "chunks_added": 2,
            "chunks_deleted": 1,
        }
        
        result = run_scheduled_scan([docs_dir], docs_manager=manager, code_manager=manager, status_dict=status_dict)

    assert result["chunks_added"] == 2
    assert status_dict["last_scan_type"] == "periodic_incremental_scan"
    assert status_dict["scheduler_status"]["last_scheduled_scan_time"] == status_dict["last_ingestion_time"]
    mock_write.assert_called_once_with(
        event_type="periodic_incremental_scan",
        result=result,
        started_at=pytest.approx(mock_write.call_args.kwargs["started_at"], abs=10),
    )


@pytest.mark.anyio
async def test_periodic_scan_scheduler_lifecycle():
    scheduler = PeriodicScanScheduler(interval_hours=6)
    assert not scheduler.is_running
    
    scheduler.start()
    assert scheduler.is_running
    assert scheduler.interval_hours == 6
    
    await scheduler.stop()
    assert not scheduler.is_running


def test_api_trigger_scheduled_scan_endpoint(test_client):
    manager = MagicMock()
    manager.get_stats.return_value = {"total_chunks": 10}

    with (
        patch("api.main.ChromaManager", return_value=manager),
        patch("api.main.run_scheduled_scan") as mock_run,
    ):
        mock_run.return_value = {
            "added_files": ["new.pdf"],
            "updated_files": [],
            "deleted_files": [],
            "skipped_files": [],
            "failed_files": {},
            "chunks_added": 5,
            "chunks_deleted": 0,
        }
        
        response = test_client.post("/api/v1/ingestion/scheduled-scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["scan_type"] == "periodic_incremental_scan"
    assert payload["result"]["chunks_added"] == 5


def test_api_ingestion_status_includes_scheduler_info(test_client):
    manager = MagicMock()
    manager.get_stats.return_value = {"total_chunks": 42}

    with patch("api.main.ChromaManager", return_value=manager):
        response = test_client.get("/api/v1/ingestion/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_chunks"] == 42
    assert "scheduler_status" in payload
    assert "last_scan_type" in payload
