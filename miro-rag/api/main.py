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

# Ensure parent directory is in path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
from config.settings import API_HOST, API_PORT


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
