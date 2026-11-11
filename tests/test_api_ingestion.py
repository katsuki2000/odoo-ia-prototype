"""Ingestion status endpoint."""

from unittest.mock import MagicMock, patch

from api.routes.ingestion import ingestion_status
from config.settings import DOCS_COLLECTION_NAME
from document_rag.vectorstore.chroma_manager import ChromaManager


def test_api_v1_ingestion_status_reports_stats():
    manager = MagicMock()
    manager.get_stats.return_value = {"total_chunks": 1}

    with patch("api.routes.ingestion.ChromaManager", return_value=manager):
        payload = ingestion_status().model_dump()

    assert payload["total_chunks"] == 1
    assert set(payload["scheduler_status"]) == {"running"}


def test_api_status_reads_the_collection_the_retrieval_uses(tmp_path):
    stored = ChromaManager(db_path=tmp_path, collection_name=DOCS_COLLECTION_NAME)
    stored.collection.add(
        ids=["chunk-1"], documents=["text"], embeddings=[[0.1] * 384], metadatas=[{"source": "doc.txt"}],
    )

    with patch("document_rag.vectorstore.chroma_manager.CHROMA_PATH", tmp_path):
        response = ingestion_status()

    assert response.total_chunks == 1
