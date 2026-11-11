"""Ingestion status endpoint."""

from fastapi import APIRouter, Depends

from api.auth import require_admin
from api.schemas import IngestionStatusResponseV1
from document_rag.ingestion.scheduler import INGESTION_STATUS
from document_rag.vectorstore.chroma_manager import ChromaManager

router = APIRouter(prefix='/api/v1', dependencies=[Depends(require_admin)])


@router.get('/ingestion/status', response_model=IngestionStatusResponseV1)
def ingestion_status():
    """Return the last Drive synchronization time and vectorstore stats."""
    return IngestionStatusResponseV1(
        last_ingestion_time=INGESTION_STATUS['last_ingestion_time'],
        total_chunks=int(ChromaManager().get_stats().get('total_chunks', 0) or 0),
        scheduler_status=INGESTION_STATUS['scheduler_status'],
    )
