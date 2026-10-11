"""
api/main.py

FastAPI REST endpoint for AI.
Exposes the pipeline and ingestion endpoints as an HTTP API.
"""

import os
import sys
import logging
from contextlib import asynccontextmanager
from typing import Any

# Ensure parent directory is in path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import get_jwt_secret
from config.settings import API_HOST, API_PORT, CORS_ALLOWED_ORIGINS
from document_rag.ingestion.ingest_all import DOCS_DIR
from document_rag.ingestion.scheduler import (
    PeriodicScanScheduler,
    run_scheduled_scan,
    run_startup_scan,
)
from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.ingestion.logging_utils import write_ingestion_event
from document_rag.vectorstore.chroma_manager import ChromaManager

from api import routes_system
from api import routes_ask
from api import routes_ingestion

logger = logging.getLogger(__name__)

# Background task handles and state dictionaries
SCHEDULER_INSTANCE: PeriodicScanScheduler | None = None
WATCHER_INSTANCE = None

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

def warm_up_code_intelligence_graph() -> None:
    """Load (or build, then swap atomically) the code intelligence graph before the first question."""
    try:
        from code_intelligence.graph.loader import get_code_intelligence_graph

        graph = get_code_intelligence_graph()
        logger.info(
            "Code intelligence graph ready: %d nodes, languages %s",
            graph.number_of_nodes(), list(graph.graph.get("translation_languages", ())),
        )
    except Exception as exc:
        logger.exception("Code intelligence graph warm-up failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle cleanly."""
    global SCHEDULER_INSTANCE
    get_jwt_secret()
    try:
        import threading
        startup_roots = [DOCS_DIR]
        logger.info("Startup incremental scan: scanning %s", startup_roots)
        t = threading.Thread(
            target=run_startup_scan,
            args=(startup_roots,),
            kwargs={"status_dict": LAST_INGESTION_STATUS},
            daemon=True,
        )
        t.start()
    except Exception as exc:
        logger.exception("Startup incremental scan failed: %s", exc)

    import threading
    threading.Thread(target=warm_up_code_intelligence_graph, daemon=True).start()

    if SCHEDULER_INSTANCE is None:
        SCHEDULER_INSTANCE = PeriodicScanScheduler(
            interval_hours=6,
            roots=[DOCS_DIR],
            docs_manager=None,
            status_dict=LAST_INGESTION_STATUS,
        )
    SCHEDULER_INSTANCE.start()
    logger.info("FINISHED startup in lifespan, returning to uvicorn!")

    yield

    if SCHEDULER_INSTANCE is not None:
        logger.info("Stopping background periodic scan scheduler...")
        await SCHEDULER_INSTANCE.stop()


app = FastAPI(
    title="MIRO AI API",
    description="REST API for querying the ERP internal knowledge base",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Accept-Language"],
)

# Mount the static UI
ui_path = os.path.join(os.path.dirname(__file__), "..", "ui")
if os.path.exists(ui_path):
    app.mount("/ui", StaticFiles(directory=ui_path, html=True), name="ui")

# Include domain routers
app.include_router(routes_system.router)
app.include_router(routes_ask.router)
app.include_router(routes_ingestion.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
