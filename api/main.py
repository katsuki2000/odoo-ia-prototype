"""FastAPI application of the MIRO AI API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import routes_ask, routes_ingestion, routes_system
from api.auth import get_jwt_secret
from config.settings import API_HOST, API_PORT, CORS_ALLOWED_ORIGINS, SCHEDULER_INTERVAL_HOURS
from document_rag.ingestion.scheduler import INGESTION_STATUS, start_scan_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_jwt_secret()
    scheduler_status = INGESTION_STATUS["scheduler_status"]
    stop_event = start_scan_loop(SCHEDULER_INTERVAL_HOURS, INGESTION_STATUS)
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

app.include_router(routes_system.router)
app.include_router(routes_ask.router)
app.include_router(routes_ingestion.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
