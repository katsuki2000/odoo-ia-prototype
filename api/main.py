"""
api/main.py

FastAPI REST endpoint for AI.
Exposes the pipeline and ingestion endpoints as an HTTP API.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import get_jwt_secret
from config.settings import API_HOST, API_PORT, CORS_ALLOWED_ORIGINS, SCHEDULER_INTERVAL_HOURS
from document_rag.ingestion.scheduler import start_scan_loop

from api import routes_system
from api import routes_ask
from api import routes_ingestion
from api.routes_ingestion import LAST_INGESTION_STATUS


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_jwt_secret()
    scheduler_status = LAST_INGESTION_STATUS["scheduler_status"]
    stop_event = start_scan_loop(SCHEDULER_INTERVAL_HOURS, LAST_INGESTION_STATUS)
    scheduler_status["running"] = True
    yield
    stop_event.set()
    scheduler_status["running"] = False


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
