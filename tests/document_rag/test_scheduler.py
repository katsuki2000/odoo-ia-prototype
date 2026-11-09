"""Periodic Drive synchronization loop: configuration gate, success, quiet cycles and failures."""

from threading import Event
from unittest.mock import patch

import pytest

from config.google_drive import GoogleDriveSettings
from document_rag.ingestion.scheduler import DRIVE_SYNC, INGESTION_STATUS, start_drive_sync_loop


@pytest.mark.parametrize("settings", [
    GoogleDriveSettings(),
    GoogleDriveSettings(folder_ids=("folder",), approved_for_rag=False),
])
def test_drive_sync_loop_stays_off_unless_configured_and_approved(settings):
    with (
        patch("document_rag.ingestion.scheduler.GoogleDriveSettings.current", return_value=settings),
        patch("document_rag.ingestion.scheduler.Thread") as mock_thread,
    ):
        start_drive_sync_loop()

    mock_thread.assert_not_called()


def test_drive_sync_loop_synchronizes_repeatedly_under_the_lock():
    settings = GoogleDriveSettings(folder_ids=("folder",), approved_for_rag=True, sync_interval=0.001)
    result = {"status": "complete", "added": ["file"], "chunks_added": 3}
    events = []
    second_event_written = Event()

    def record(**event):
        events.append(event)
        if len(events) == 2:
            second_event_written.set()

    with (
        patch("document_rag.ingestion.scheduler.GoogleDriveSettings.current", return_value=settings),
        patch("document_rag.ingestion.scheduler.ChromaManager"),
        patch("document_rag.ingestion.scheduler.drive_sync_lock") as mock_lock,
        patch("document_rag.ingestion.scheduler.configured_synchronizer", return_value=lambda: result) as mock_build,
        patch("document_rag.ingestion.scheduler.write_ingestion_event", side_effect=record),
    ):
        stop_event = start_drive_sync_loop()
        assert second_event_written.wait(timeout=5)
        stop_event.set()

    assert mock_build.call_args.args[0] == settings
    assert mock_lock.return_value.__enter__.call_count >= 2
    assert events[0] == {"event_type": DRIVE_SYNC, "result": result, "status": "success"}


def test_drive_sync_loop_writes_nothing_when_nothing_changed():
    settings = GoogleDriveSettings(folder_ids=("folder",), approved_for_rag=True, sync_interval=0.001)
    calls = []
    second_sync_started = Event()

    def synchronize():
        calls.append(True)
        if len(calls) == 2:
            second_sync_started.set()
        return {"status": "complete", "added": [], "updated": [], "skipped": ["file"], "failed": {},
                "chunks_added": 0, "chunks_deleted": 0}

    with (
        patch.dict(INGESTION_STATUS, {"last_ingestion_time": None}),
        patch("document_rag.ingestion.scheduler.GoogleDriveSettings.current", return_value=settings),
        patch("document_rag.ingestion.scheduler.ChromaManager"),
        patch("document_rag.ingestion.scheduler.drive_sync_lock"),
        patch("document_rag.ingestion.scheduler.configured_synchronizer", return_value=synchronize),
        patch("document_rag.ingestion.scheduler.write_ingestion_event") as mock_write,
    ):
        stop_event = start_drive_sync_loop()
        assert second_sync_started.wait(timeout=5)
        stop_event.set()
        last_ingestion_time = INGESTION_STATUS["last_ingestion_time"]

    mock_write.assert_not_called()
    assert last_ingestion_time is not None


def test_drive_sync_failure_is_logged_as_an_error():
    settings = GoogleDriveSettings(folder_ids=("folder",), approved_for_rag=True, sync_interval=0.001)
    written = Event()
    events = []

    def record(**event):
        events.append(event)
        written.set()

    def fail():
        raise TimeoutError

    with (
        patch("document_rag.ingestion.scheduler.GoogleDriveSettings.current", return_value=settings),
        patch("document_rag.ingestion.scheduler.ChromaManager"),
        patch("document_rag.ingestion.scheduler.drive_sync_lock"),
        patch("document_rag.ingestion.scheduler.configured_synchronizer", return_value=fail),
        patch("document_rag.ingestion.scheduler.write_ingestion_event", side_effect=record),
    ):
        stop_event = start_drive_sync_loop()
        assert written.wait(timeout=5)
        stop_event.set()

    assert events[0]["status"] == "error"
    assert events[0]["result"] == {"status": "failed", "error_type": "TimeoutError"}
