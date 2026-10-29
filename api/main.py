"""
api/main.py

FastAPI REST endpoint for AI.
Exposes the pipeline and ingestion endpoints as an HTTP API.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import get_jwt_secret
from config.settings import API_HOST, API_PORT, CORS_ALLOWED_ORIGINS, SCHEDULER_INTERVAL_HOURS
from document_rag.ingestion.ingest_all import DOCS_DIR
from document_rag.ingestion.scheduler import (
    PeriodicScanScheduler,
    run_startup_scan,
)

from api import routes_system
from api import routes_ask
from api import routes_ingestion
from api.routes_ingestion import LAST_INGESTION_STATUS

logger = logging.getLogger(__name__)

# Background task handles and state dictionaries
SCHEDULER_INSTANCE: PeriodicScanScheduler | None = None


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

    if SCHEDULER_INSTANCE is None:
        SCHEDULER_INSTANCE = PeriodicScanScheduler(
            interval_hours=SCHEDULER_INTERVAL_HOURS,
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
