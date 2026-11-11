"""FastAPI application of the MIRO AI API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import ask, ingestion, system
from api.auth import get_jwt_secret
from config.settings import API_HOST, API_PORT, CORS_ALLOWED_ORIGINS
from document_rag.ingestion.scheduler import INGESTION_STATUS, start_drive_sync_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_jwt_secret()
    stop_event = start_drive_sync_loop()
    yield
    stop_event.set()
    INGESTION_STATUS['scheduler_status']['running'] = False


app = FastAPI(
    title='MIRO AI API',
    description='REST API for querying the ERP internal knowledge base',
    version='1.0.0',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=['GET', 'POST'],
    allow_headers=['Authorization', 'Content-Type', 'Accept-Language'],
)

app.include_router(system.router)
app.include_router(ask.router)
app.include_router(ingestion.router)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
