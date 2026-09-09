"""Ingestion and reindexing endpoints and helper utilities."""

import logging
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from api.schemas import (
    IngestionStatusResponse,
    ReindexRequestV1,
    ReindexResponse,
    ReindexResponseV1,
    ScheduledScanResponse,
)
from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.ingestion.ingest_all import DOCS_DIR, IngestionOrchestrator
from document_rag.ingestion.logging_utils import now_iso, start_timer, write_ingestion_event
from document_rag.ingestion.scheduler import run_scheduled_scan
from document_rag.ingestion.watcher import DEFAULT_DOCS_DIR
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

router = APIRouter()


def _main_ref(name: str, fallback: Any) -> Any:
    main = sys.modules.get("api.main")
    if main and hasattr(main, name):
        return getattr(main, name)
    return fallback


@router.post("/reindex", response_model=ReindexResponse)
def reindex():
    """Re-ingest all documents into the vectorstore."""
    from document_rag.ingestion.pdf_loader import load_all
    from document_rag.vectorstore.chroma_manager import (
        add_documents,
        get_chroma_client,
        get_collection_stats,
        reset_collection,
    )

    try:
        documents, metadatas, ids = load_all()
        if not documents:
            raise HTTPException(status_code=500, detail="No documents found for ingestion")

        client = get_chroma_client()
        collection = reset_collection(client, "miro_knowledge_base")

        batch_size = 50
        for i in range(0, len(documents), batch_size):
            add_documents(
                collection,
                documents[i:i + batch_size],
                metadatas[i:i + batch_size],
                ids[i:i + batch_size],
            )

        stats = get_collection_stats(collection)
        return ReindexResponse(
            status="success",
            document_count=stats["document_count"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reindex failed: {str(e)}")


@router.post("/api/v1/reindex", response_model=ReindexResponseV1)
def reindex_v1(request: ReindexRequestV1):
    """Trigger full or incremental ingestion."""
    started_at = start_timer()
    chroma_cls = _main_ref("ChromaManager", ChromaManager)
    manager = chroma_cls()
    target_path = Path(request.path).resolve() if request.path else None

    reindex_fn = _main_ref("reindex_if_changed", reindex_if_changed)
    write_event_fn = _main_ref("write_ingestion_event", write_ingestion_event)
    status_dict = _main_ref("LAST_INGESTION_STATUS", {})

    try:
        if request.scope == "incremental":
            roots = [target_path] if target_path else [DOCS_DIR]
            result = reindex_fn(roots, docs_manager=manager, code_manager=manager)
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
        write_event_fn(
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
        write_event_fn(
            event_type=f"api_reindex_{request.scope}",
            result=result,
            started_at=started_at,
            status="error",
        )
        raise HTTPException(status_code=500, detail=f"Reindex failed: {str(e)}")


@router.get("/api/v1/ingestion/status", response_model=IngestionStatusResponse)
def ingestion_status():
    """Return ingestion status, vectorstore stats, and watcher state."""
    chroma_cls = _main_ref("ChromaManager", ChromaManager)
    manager = chroma_cls()
    stats = manager.get_stats()
    watcher_status = _get_watcher_status()
    status_dict = _main_ref("LAST_INGESTION_STATUS", {})

    return IngestionStatusResponse(
        last_ingestion_time=status_dict.get("last_ingestion_time"),
        total_chunks=int(stats.get("total_chunks", 0) or 0),
        files_monitored=_count_supported_files([DEFAULT_DOCS_DIR]),
        watcher_status=watcher_status,
        scheduler_status=status_dict.get("scheduler_status"),
        last_scan_type=status_dict.get("last_scan_type"),
    )


@router.post("/api/v1/ingestion/scheduled-scan", response_model=ScheduledScanResponse)
def trigger_scheduled_scan():
    """Manually trigger one execution of the 6-hour scheduled periodic incremental scan."""
    try:
        chroma_cls = _main_ref("ChromaManager", ChromaManager)
        manager = chroma_cls()
        scan_fn = _main_ref("run_scheduled_scan", run_scheduled_scan)
        status_dict = _main_ref("LAST_INGESTION_STATUS", {})
        result = scan_fn([DOCS_DIR], docs_manager=manager, code_manager=manager, status_dict=status_dict)
        return ScheduledScanResponse(
            status="success",
            scan_type="periodic_incremental_scan",
            result=result,
            last_ingestion_time=status_dict.get("last_ingestion_time"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scheduled scan failed: {str(exc)}")


def _count_supported_files(paths: list[Path]) -> int:
    """Count files monitored by the ingestion watcher."""
    supported_extensions = {".pdf", ".txt", ".md"}
    count = 0
    for path in paths:
        if path.is_file() and path.suffix.lower() in supported_extensions:
            count += 1
        elif path.is_dir():
            count += sum(
                1
                for file_path in path.rglob("*")
                if file_path.is_file() and file_path.suffix.lower() in supported_extensions
            )
    return count


def _get_watcher_status() -> dict[str, Any]:
    """Return watcher status without starting a watcher implicitly."""
    watcher = _main_ref("WATCHER_INSTANCE", None)
    if watcher is not None:
        return watcher.status()

    return {
        "watched_paths": [],
        "watcher_running": False,
        "last_event_path": None,
        "last_event_type": None,
        "last_result": None,
        "errors": [],
    }
