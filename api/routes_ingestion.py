"""Ingestion and reindexing endpoints."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_admin
from api.public_errors import public_error_details
from api.schemas import (
    IngestionStatusResponse,
    ReindexRequestV1,
    ReindexResponseV1,
    ScheduledScanResponse,
)
from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.ingestion.ingest_all import IngestionOrchestrator
from document_rag.ingestion.logging_utils import now_iso, start_timer, write_ingestion_event
from document_rag.ingestion.scan_root import DOCS_DIR, confine_to_scan_roots
from document_rag.ingestion.scheduler import INGESTION_STATUS, PERIODIC_SCAN, run_scan
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin)])


def _resolve_reindex_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    try:
        return confine_to_scan_roots(raw_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _total_chunks(manager: ChromaManager) -> int:
    return int(manager.get_stats().get("total_chunks", 0) or 0)


def _count_supported_files(directory: Path) -> int:
    return sum(is_supported_document(path) for path in directory.rglob("*") if path.is_file())


def _public_http_error(exc: Exception) -> HTTPException:
    status_code, detail = public_error_details(exc)
    return HTTPException(status_code=status_code, detail=detail)


@router.post("/api/v1/reindex", response_model=ReindexResponseV1)
def reindex_v1(request: ReindexRequestV1):
    """Trigger full or incremental ingestion."""
    started_at = start_timer()
    manager = ChromaManager()
    target_path = _resolve_reindex_path(request.path)
    event_type = f"api_reindex_{request.scope}"

    try:
        if request.scope == "incremental":
            result = reindex_if_changed([target_path or DOCS_DIR], docs_manager=manager)
        else:
            docs_dir = target_path or DOCS_DIR
            result = IngestionOrchestrator(
                chroma_db_path=manager.db_path,
                collection_name=manager.collection_name,
            ).clear_and_reingest(docs_dir=docs_dir.parent if docs_dir.is_file() else docs_dir)
    except Exception as exc:
        logger.exception("Reindex failed.")
        write_ingestion_event(
            event_type=event_type,
            result={"failed_files": {str(target_path or "default_roots"): str(exc)}},
            started_at=started_at,
            status="error",
        )
        raise _public_http_error(exc) from None

    INGESTION_STATUS["last_ingestion_time"] = now_iso()
    INGESTION_STATUS["last_result"] = result
    write_ingestion_event(event_type=event_type, result=result, started_at=started_at)
    return ReindexResponseV1(
        status="success",
        scope=request.scope,
        result=result,
        total_chunks=_total_chunks(manager),
    )


@router.get("/api/v1/ingestion/status", response_model=IngestionStatusResponse)
def ingestion_status():
    """Return ingestion status and vectorstore stats."""
    return IngestionStatusResponse(
        last_ingestion_time=INGESTION_STATUS["last_ingestion_time"],
        total_chunks=_total_chunks(ChromaManager()),
        files_monitored=_count_supported_files(DOCS_DIR),
        scheduler_status=INGESTION_STATUS["scheduler_status"],
        last_scan_type=INGESTION_STATUS["last_scan_type"],
    )


@router.post("/api/v1/ingestion/scheduled-scan", response_model=ScheduledScanResponse)
def trigger_scheduled_scan():
    """Manually trigger one incremental scan of the documents folder."""
    try:
        result = run_scan(
            PERIODIC_SCAN, [DOCS_DIR], docs_manager=ChromaManager(), status_dict=INGESTION_STATUS,
        )
    except Exception as exc:
        logger.exception("Scheduled scan failed.")
        raise _public_http_error(exc) from None
    return ScheduledScanResponse(
        status="success",
        scan_type=PERIODIC_SCAN,
        result=result,
        last_ingestion_time=INGESTION_STATUS["last_ingestion_time"],
    )
