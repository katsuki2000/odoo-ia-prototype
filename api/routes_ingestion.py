"""Ingestion and reindexing endpoints and helper utilities."""

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_admin
from config.settings import SCHEDULER_INTERVAL_HOURS
from api.schemas import (
    IngestionStatusResponse,
    ReindexRequestV1,
    ReindexResponseV1,
    ScheduledScanResponse,
)
from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.ingestion.ingest_all import DOCS_DIR, IngestionOrchestrator
from document_rag.ingestion.logging_utils import now_iso, start_timer, write_ingestion_event
from document_rag.ingestion.scan_root import confine_to_scan_roots
from document_rag.ingestion.scheduler import run_scheduled_scan
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin)])


LAST_INGESTION_STATUS: dict[str, Any] = {
    "last_ingestion_time": None,
    "last_result": None,
    "last_scan_type": None,
    "scheduler_status": {
        "interval_hours": SCHEDULER_INTERVAL_HOURS,
        "running": False,
        "last_startup_scan_time": None,
        "last_scheduled_scan_time": None,
    },
}


def _resolve_reindex_path(raw_path: Optional[str]) -> Optional[Path]:
    if not raw_path:
        return None
    try:
        return confine_to_scan_roots(raw_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/reindex", response_model=ReindexResponseV1)
def reindex_v1(request: ReindexRequestV1):
    """Trigger full or incremental ingestion."""
    started_at = start_timer()
    manager = ChromaManager()
    target_path = _resolve_reindex_path(request.path)

    status_dict = LAST_INGESTION_STATUS

    try:
        if request.scope == "incremental":
            roots = [target_path] if target_path else [DOCS_DIR]
            result = reindex_if_changed(roots, docs_manager=manager)
        elif request.scope == "full":
            orchestrator = IngestionOrchestrator(
                chroma_db_path=manager.db_path,
                collection_name=manager.collection_name,
            )
            docs_dir = (target_path.parent if target_path.is_file() else target_path) if target_path else DOCS_DIR
            result = orchestrator.clear_and_reingest(
                docs_dir=docs_dir,
                incremental=False,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported reindex scope: {request.scope}")

        stats = manager.get_stats()
        status_dict["last_ingestion_time"] = now_iso()
        status_dict["last_result"] = result
        write_ingestion_event(
            event_type=f"api_reindex_{request.scope}",
            result=result,
            started_at=started_at,
        )
        return ReindexResponseV1(
            status="success",
            scope=request.scope,
            result=result,
            total_chunks=int(stats.get("total_chunks", 0) or 0),
        )
    except HTTPException:
        raise
    except Exception as e:
        result = {"failed_files": {str(target_path or "default_roots"): str(e)}}
        write_ingestion_event(
            event_type=f"api_reindex_{request.scope}",
            result=result,
            started_at=started_at,
            status="error",
        )
        raise HTTPException(status_code=500, detail=f"Reindex failed: {str(e)}")


@router.get("/api/v1/ingestion/status", response_model=IngestionStatusResponse)
def ingestion_status():
    """Return ingestion status, vectorstore stats, and watcher state."""
    manager = ChromaManager()
    stats = manager.get_stats()
    watcher_status = _get_watcher_status()
    status_dict = LAST_INGESTION_STATUS

    return IngestionStatusResponse(
        last_ingestion_time=status_dict.get("last_ingestion_time"),
        total_chunks=int(stats.get("total_chunks", 0) or 0),
        files_monitored=_count_supported_files([DOCS_DIR]),
        watcher_status=watcher_status,
        scheduler_status=status_dict.get("scheduler_status"),
        last_scan_type=status_dict.get("last_scan_type"),
    )


@router.post("/api/v1/ingestion/scheduled-scan", response_model=ScheduledScanResponse)
def trigger_scheduled_scan():
    """Manually trigger one execution of the 6-hour scheduled periodic incremental scan."""
    try:
        manager = ChromaManager()
        status_dict = LAST_INGESTION_STATUS
        result = run_scheduled_scan([DOCS_DIR], docs_manager=manager, status_dict=status_dict)
        return ScheduledScanResponse(
            status="success",
            scan_type="periodic_incremental_scan",
            result=result,
            last_ingestion_time=status_dict.get("last_ingestion_time"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scheduled scan failed: {str(exc)}")


def _count_supported_files(paths: list[Path]) -> int:
    """Count the documents of a supported format under the given files and directories."""
    count = 0
    for path in paths:
        if path.is_file() and is_supported_document(path):
            count += 1
        elif path.is_dir():
            count += sum(1 for file_path in path.rglob("*") if file_path.is_file() and is_supported_document(file_path))
    return count


def _get_watcher_status() -> dict[str, Any]:
    """Return the idle watcher status; the API never starts a watcher."""
    return {
        "watched_paths": [],
        "watcher_running": False,
        "last_event_path": None,
        "last_event_type": None,
        "last_result": None,
        "errors": [],
    }
