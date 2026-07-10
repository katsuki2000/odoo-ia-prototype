"""
ingestion/scheduler.py

Scheduler and periodic incremental scanning for the RAG pipeline.
Handles startup catch-up scanning and periodic background scans (e.g., every 6 hours).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ingestion.incremental import reindex_if_changed
from ingestion.logging_utils import now_iso, start_timer, write_ingestion_event
from vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

# Default roots if none provided
from ingestion.ingest_all import CODE_DIR, DOCS_DIR
DEFAULT_SCAN_ROOTS = [DOCS_DIR, CODE_DIR]


def run_startup_scan(
    roots: list[Path | str] | None = None,
    chroma_manager: ChromaManager | None = None,
    status_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run one incremental scan on application startup.
    Catches and indexes any file changes made while the system was offline.
    """
    started_at = start_timer()
    target_roots = roots if roots is not None else DEFAULT_SCAN_ROOTS
    manager = chroma_manager or ChromaManager()

    logger.info("Running startup incremental scan across roots: %s", target_roots)
    result = reindex_if_changed(target_roots, chroma_manager=manager)

    if status_dict is not None:
        status_dict["last_ingestion_time"] = now_iso()
        status_dict["last_result"] = result
        status_dict["last_scan_type"] = "startup_incremental_scan"
        if "scheduler_status" in status_dict and isinstance(status_dict["scheduler_status"], dict):
            status_dict["scheduler_status"]["last_startup_scan_time"] = status_dict["last_ingestion_time"]

    write_ingestion_event(
        event_type="startup_incremental_scan",
        result=result,
        started_at=started_at,
    )
    logger.info("Startup incremental scan completed: %s", result)
    return result


def run_scheduled_scan(
    roots: list[Path | str] | None = None,
    chroma_manager: ChromaManager | None = None,
    status_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run the scheduled full incremental scan against ChromaDB inventory.
    Catches any changes missed by the watcher or external edits.
    """
    started_at = start_timer()
    target_roots = roots if roots is not None else DEFAULT_SCAN_ROOTS
    manager = chroma_manager or ChromaManager()

    logger.info("Running scheduled incremental scan across roots: %s", target_roots)
    result = reindex_if_changed(target_roots, chroma_manager=manager)

    if status_dict is not None:
        status_dict["last_ingestion_time"] = now_iso()
        status_dict["last_result"] = result
        status_dict["last_scan_type"] = "periodic_incremental_scan"
        if "scheduler_status" in status_dict and isinstance(status_dict["scheduler_status"], dict):
            status_dict["scheduler_status"]["last_scheduled_scan_time"] = status_dict["last_ingestion_time"]

    write_ingestion_event(
        event_type="periodic_incremental_scan",
        result=result,
        started_at=started_at,
    )
    logger.info("Scheduled incremental scan completed: %s", result)
    return result


class PeriodicScanScheduler:
    """Manages periodic background incremental scanning."""

    def __init__(
        self,
        interval_hours: int = 6,
        roots: list[Path | str] | None = None,
        chroma_manager: ChromaManager | None = None,
        status_dict: dict[str, Any] | None = None,
    ) -> None:
        self.interval_hours = interval_hours
        self.roots = roots if roots is not None else DEFAULT_SCAN_ROOTS
        self.chroma_manager = chroma_manager
        self.status_dict = status_dict
        self._task: asyncio.Task[Any] | None = None
        self._running = False

    async def _loop(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(self.interval_hours * 3600)
            if not self._running:
                break
            try:
                manager = self.chroma_manager or ChromaManager()
                await asyncio.to_thread(
                    run_scheduled_scan,
                    self.roots,
                    manager,
                    self.status_dict,
                )
            except Exception as exc:
                logger.exception("Scheduled periodic scan failed: %s", exc)

    def start(self) -> None:
        """Start the periodic background scanning loop."""
        if self._task is None or self._task.done():
            self._running = True
            if self.status_dict and "scheduler_status" in self.status_dict and isinstance(self.status_dict["scheduler_status"], dict):
                self.status_dict["scheduler_status"]["running"] = True
                self.status_dict["scheduler_status"]["interval_hours"] = self.interval_hours
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop and cleanly cancel the background scanning loop."""
        self._running = False
        if self.status_dict and "scheduler_status" in self.status_dict and isinstance(self.status_dict["scheduler_status"], dict):
            self.status_dict["scheduler_status"]["running"] = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def is_running(self) -> bool:
        """Check if the background task is active."""
        return self._running and self._task is not None and not self._task.done()
