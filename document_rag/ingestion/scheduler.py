"""Periodic synchronization of the approved Drive folders into the index."""

import logging
from threading import Event, Thread
from typing import Any

from config.google_drive import GoogleDriveSettings
from document_rag.ingestion.google_drive_sync import configured_synchronizer, drive_sync_lock
from document_rag.ingestion.logging_utils import now_iso, write_ingestion_event
from document_rag.ingestion.periodic import run_periodically
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

DRIVE_SYNC = "drive_sync"

INGESTION_STATUS: dict[str, Any] = {
    "last_ingestion_time": None,
    "scheduler_status": {"running": False},
}


def start_drive_sync_loop():
    """Synchronize the approved Drive folders now, then periodically, in a daemon thread.

    The API process is the only writer of the index: a second writing process leaves the API with a stale one.
    """
    stop_event = Event()
    settings = GoogleDriveSettings.current()
    if not settings.folder_ids or not settings.approved_for_rag:
        logger.info("Drive synchronization off: set GOOGLE_DRIVE_FOLDER_IDS and GOOGLE_DRIVE_APPROVED_FOR_RAG=true.")
        return stop_event

    def synchronize():
        manager = ChromaManager()
        with drive_sync_lock(manager):
            return configured_synchronizer(settings, manager)()

    def report(result):
        complete = result.get("status") == "complete"
        (logger.info if complete else logger.warning)("Drive synchronization: %s", result)
        if complete:
            INGESTION_STATUS["last_ingestion_time"] = now_iso()
        if not complete or any(result.get(key) for key in ("added", "updated", "chunks_deleted")):
            write_ingestion_event(event_type=DRIVE_SYNC, result=result, status="success" if complete else "error")

    Thread(target=run_periodically, args=(synchronize, settings.sync_interval, report, stop_event), daemon=True).start()
    INGESTION_STATUS["scheduler_status"]["running"] = True
    return stop_event
