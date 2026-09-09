"""System, health check, module coverage, and statistics endpoints."""

import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from api.schemas import ModuleCoverageResponse, StatsResponse

router = APIRouter()


@router.get("/", include_in_schema=False)
def root():
    """Redirect root URL to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")


@router.get("/health")
def health_check():
    """Basic health check to verify the API is running."""
    return {"status": "ok", "service": "miro-rag-api"}


@router.get("/api/v1/health")
def health_check_v1():
    """V1 health check verifying underlying services."""
    from document_rag.vectorstore.chroma_manager import get_chroma_client
    from erp_data.odoo_connector import OdooConnector

    status = {"status": "ok", "services": {}}

    try:
        client = get_chroma_client()
        client.heartbeat()
        status["services"]["chroma"] = "ok"
    except Exception:
        status["services"]["chroma"] = "error"
        status["status"] = "degraded"

    try:
        connector = OdooConnector()
        connector.authenticate("admin")
        status["services"]["odoo"] = "ok"
    except Exception:
        status["services"]["odoo"] = "error"
        status["status"] = "degraded"

    from config.settings import LLM_PROVIDER, LOCAL_LLM_BASE_URL, OPENROUTER_API_KEY
    provider = (LLM_PROVIDER or "groq").lower().strip()
    if provider in ("local", "ollama", "vllm", "openai_compatible", "lmstudio", "llamacpp"):
        status["services"]["llm"] = f"ok (local: {LOCAL_LLM_BASE_URL})"
        status["services"]["groq"] = "ok (provider: local)"
    elif provider == "openrouter":
        if not OPENROUTER_API_KEY:
            status["services"]["llm"] = "error (no openrouter key)"
            status["services"]["groq"] = "error (no key)"
            status["status"] = "degraded"
        else:
            status["services"]["llm"] = "ok (openrouter)"
            status["services"]["groq"] = "ok (provider: openrouter)"
    else:
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            status["services"]["groq"] = "error (no key)"
            status["services"]["llm"] = "error (no groq key)"
            status["status"] = "degraded"
        else:
            status["services"]["groq"] = "ok"
            status["services"]["llm"] = "ok (groq)"

    return status


@router.get("/api/v1/modules", response_model=ModuleCoverageResponse)
def get_modules():
    """Get module coverage data comparing installed Odoo modules against AI capabilities."""
    from erp_data.odoo_connector import OdooConnector
    try:
        connector = OdooConnector()
        uid = connector.authenticate("admin")
        records = connector.search_read(
            uid=uid,
            model="ir.module.module",
            domain=[("state", "=", "installed")],
            fields=["name"]
        )
        installed = {r["name"] for r in records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Odoo error: {str(e)}")

    supported = ["sale", "account", "helpdesk", "project", "stock"]
    code_indexed = ["sale", "account", "helpdesk", "project", "stock", "base"]

    actual_supported = [m for m in supported if m in installed]
    actual_code_indexed = [m for m in code_indexed if m in installed and m not in actual_supported]
    not_covered = [m for m in installed if m not in supported and m not in code_indexed]

    return ModuleCoverageResponse(
        supported=actual_supported,
        code_indexed=actual_code_indexed,
        not_covered=not_covered
    )


@router.get("/stats", response_model=StatsResponse)
def get_stats():
    """Return statistics about the current vectorstore collection."""
    from document_rag.vectorstore.chroma_manager import (
        get_chroma_client,
        get_or_create_collection,
        get_collection_stats,
    )

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
