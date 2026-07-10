"""
api/main.py

FastAPI REST endpoint for the MIRO RAG assistant.
Exposes the RAG pipeline as an HTTP API so that the Odoo module
and other clients can query the knowledge base.

Endpoints:
    POST /ask          - Submit a question and receive an AI-generated answer
    GET  /health       - Health check
    GET  /stats        - Collection statistics
    POST /reindex      - Trigger vectorstore re-ingestion
"""

import os
import sys
from pathlib import Path

# Ensure parent directory is in path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from config.settings import API_HOST, API_PORT
import asyncio
import logging
from ingestion.ingest_all import CODE_DIR, DOCS_DIR, IngestionOrchestrator
from ingestion.incremental import reindex_if_changed
from ingestion.logging_utils import now_iso, start_timer, write_ingestion_event
from ingestion.watcher import DEFAULT_CODE_DIR, DEFAULT_DOCS_DIR
from ingestion.scheduler import PeriodicScanScheduler, run_scheduled_scan, run_startup_scan
from vectorstore.chroma_manager import ChromaManager

# Background task handle for scheduled scans
SCHEDULER_INSTANCE: PeriodicScanScheduler | None = None


app = FastAPI(
    title="MIRO RAG Assistant API",
    description="REST API for querying the MIRO KE internal knowledge base using RAG.",
    version="1.0.0",
)

# Allow CORS for Odoo frontend and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Request and Response Models --

class AskRequest(BaseModel):
    """Request body for the /ask endpoint."""
    question: str = Field(..., min_length=1, description="The user's question in natural language")
    n_results: int = Field(5, ge=1, le=20, description="Number of documents to retrieve")
    filter_type: Optional[str] = Field(None, description="Filter by document type: wiki, ticket, sale, manual")


class Source(BaseModel):
    """A single source document reference."""
    source: str
    type: str
    title: str
    snippet: Optional[str] = None


class AskResponse(BaseModel):
    """Response body for the /ask endpoint."""
    answer: str
    question: str
    sources: list[Source]


class StatsResponse(BaseModel):
    """Response body for the /stats endpoint."""
    collection_name: str
    document_count: int


class ReindexResponse(BaseModel):
    """Response body for the /reindex endpoint."""
    status: str
    document_count: int


class ReindexRequestV1(BaseModel):
    """Request body for /api/v1/reindex."""
    scope: Literal["full", "incremental"] = Field(
        "incremental",
        description="Use 'full' to clear/rebuild or 'incremental' to process changes only",
    )
    path: Optional[str] = Field(
        None,
        description="Optional file or directory path to process",
    )


class ReindexResponseV1(BaseModel):
    """Response body for /api/v1/reindex."""
    status: str
    scope: str
    result: dict[str, Any]
    total_chunks: int


class IngestionStatusResponse(BaseModel):
    """Response body for /api/v1/ingestion/status."""
    last_ingestion_time: Optional[str]
    total_chunks: int
    files_monitored: int
    watcher_status: dict[str, Any]
    scheduler_status: Optional[dict[str, Any]] = None
    last_scan_type: Optional[str] = None


class ScheduledScanResponse(BaseModel):
    """Response body for triggering or checking scheduled scan."""
    status: str
    scan_type: str
    result: dict[str, Any]
    last_ingestion_time: Optional[str]


LAST_INGESTION_STATUS: dict[str, Any] = {
    "last_ingestion_time": None,
    "last_result": None,
    "last_scan_type": None,
    "scheduler_status": {
        "interval_hours": 6,
        "running": False,
        "last_startup_scan_time": None,
        "last_scheduled_scan_time": None,
    },
}
WATCHER_INSTANCE = None


# -- Endpoints --

@app.get("/", include_in_schema=False)
def root():
    """Redirect root URL to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health")
def health_check():
    """Basic health check to verify the API is running."""
    return {"status": "ok", "service": "miro-rag-api"}


@app.get("/stats", response_model=StatsResponse)
def get_stats():
    """Return statistics about the current vectorstore collection."""
    from vectorstore.chroma_manager import get_chroma_client, get_or_create_collection, get_collection_stats

    try:
        client = get_chroma_client()
        collection = get_or_create_collection(client)
        stats = get_collection_stats(collection)
        return StatsResponse(
            collection_name=stats["name"],
            document_count=stats["document_count"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve stats: {str(e)}")


@app.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest):
    """
    Submit a question to the RAG pipeline.

    Retrieves relevant documents from ChromaDB, builds a context-enriched
    prompt, and generates an answer via the configured LLM.
    """
    from rag.pipeline import ask

    where_filter = None
    if request.filter_type:
        where_filter = {"type": request.filter_type}

    try:
        result = ask(
            question=request.question,
            n_results=request.n_results,
            where_filter=where_filter,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {str(e)}")

    sources = [Source(**s) for s in result.get("sources", [])]

    return AskResponse(
        answer=result["answer"],
        question=result["question"],
        sources=sources,
    )


@app.post("/reindex", response_model=ReindexResponse)
def reindex():
    """
    Re-ingest all documents into the vectorstore.

    Reloads all data sources, resets the ChromaDB collection,
    and re-embeds all document chunks.
    """
    from ingestion.pdf_loader import load_all
    from vectorstore.chroma_manager import (
        get_chroma_client, reset_collection, add_documents, get_collection_stats
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


@app.post("/api/v1/reindex", response_model=ReindexResponseV1)
def reindex_v1(request: ReindexRequestV1):
    """
    Trigger full or incremental ingestion.

    Expected payload:
        {"scope": "full" | "incremental", "path": "optional/specific/path"}
    """
    started_at = start_timer()
    manager = ChromaManager()
    target_path = Path(request.path).resolve() if request.path else None

    try:
        if request.scope == "incremental":
            roots = [target_path] if target_path else [DOCS_DIR, CODE_DIR]
            result = reindex_if_changed(roots, chroma_manager=manager)
        elif request.scope == "full":
            orchestrator = IngestionOrchestrator(
                chroma_db_path=manager.db_path,
                collection_name=manager.collection_name,
            )
            if target_path:
                docs_dir, code_dir = _classify_reindex_path(target_path)
                result = orchestrator.clear_and_reingest(
                    docs_dir=docs_dir,
                    code_dir=code_dir,
                    incremental=False,
                )
            else:
                result = orchestrator.clear_and_reingest(
                    docs_dir=DOCS_DIR,
                    code_dir=CODE_DIR,
                    incremental=False,
                )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported reindex scope: {request.scope}")

        stats = manager.get_stats()
        LAST_INGESTION_STATUS["last_ingestion_time"] = now_iso()
        LAST_INGESTION_STATUS["last_result"] = result
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


@app.get("/api/v1/ingestion/status", response_model=IngestionStatusResponse)
def ingestion_status():
    """Return ingestion status, vectorstore stats, and watcher state."""
    manager = ChromaManager()
    stats = manager.get_stats()
    watcher_status = _get_watcher_status()

    return IngestionStatusResponse(
        last_ingestion_time=LAST_INGESTION_STATUS.get("last_ingestion_time"),
        total_chunks=int(stats.get("total_chunks", 0) or 0),
        files_monitored=_count_supported_files([DEFAULT_DOCS_DIR, DEFAULT_CODE_DIR]),
        watcher_status=watcher_status,
        scheduler_status=LAST_INGESTION_STATUS.get("scheduler_status"),
        last_scan_type=LAST_INGESTION_STATUS.get("last_scan_type"),
    )


@app.post("/api/v1/ingestion/scheduled-scan", response_model=ScheduledScanResponse)
def trigger_scheduled_scan():
    """Manually trigger one execution of the 6-hour scheduled periodic incremental scan."""
    try:
        manager = ChromaManager()
        result = run_scheduled_scan([DOCS_DIR, CODE_DIR], manager, LAST_INGESTION_STATUS)
        return ScheduledScanResponse(
            status="success",
            scan_type="periodic_incremental_scan",
            result=result,
            last_ingestion_time=LAST_INGESTION_STATUS.get("last_ingestion_time"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scheduled scan failed: {str(exc)}")


def _classify_reindex_path(target_path: Path) -> tuple[Path | str, Path | str]:
    """Classify a full-reindex path as docs or code input for the orchestrator."""
    if target_path.suffix.lower() in {".py", ".xml"}:
        return "", target_path.parent

    if target_path.is_dir():
        has_code = any(target_path.rglob("*.py")) or any(target_path.rglob("*.xml"))
        has_docs = any(target_path.rglob("*.pdf")) or any(target_path.rglob("*.txt")) or any(target_path.rglob("*.md"))
        if has_code and not has_docs:
            return "", target_path

    return target_path.parent if target_path.is_file() else target_path, ""


def _count_supported_files(paths: list[Path]) -> int:
    """Count files monitored by the ingestion watcher."""
    supported_extensions = {".pdf", ".txt", ".md", ".py", ".xml"}
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
    if WATCHER_INSTANCE is not None:
        return WATCHER_INSTANCE.status()

    return {
        "watched_paths": [],
        "watcher_running": False,
        "last_event_path": None,
        "last_event_type": None,
        "last_result": None,
        "errors": [],
    }


@app.on_event("startup")
async def _startup_scan_and_scheduler() -> None:
    """Run one incremental scan at startup and schedule periodic scans."""
    global SCHEDULER_INSTANCE
    logger = logging.getLogger(__name__)

    try:
        logger.info("Startup incremental scan: scanning %s and %s", DOCS_DIR, CODE_DIR)
        await asyncio.to_thread(
            run_startup_scan,
            [DOCS_DIR, CODE_DIR],
            None,
            LAST_INGESTION_STATUS,
        )
    except Exception as exc:
        logger.exception("Startup incremental scan failed: %s", exc)

    if SCHEDULER_INSTANCE is None:
        SCHEDULER_INSTANCE = PeriodicScanScheduler(
            interval_hours=6,
            roots=[DOCS_DIR, CODE_DIR],
            chroma_manager=None,
            status_dict=LAST_INGESTION_STATUS,
        )
    SCHEDULER_INSTANCE.start()


@app.on_event("shutdown")
async def _shutdown_cancel_tasks() -> None:
    """Cancel background tasks cleanly on shutdown."""
    global SCHEDULER_INSTANCE
    logger = logging.getLogger(__name__)
    if SCHEDULER_INSTANCE is not None:
        logger.info("Stopping background periodic scan scheduler...")
        await SCHEDULER_INSTANCE.stop()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
