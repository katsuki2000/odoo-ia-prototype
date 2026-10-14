"""System, health check, module coverage, and statistics endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from api.auth import get_current_user, require_admin
from api.public_errors import public_error_details
from api.schemas import ModuleCoverageResponse, StatsResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", include_in_schema=False)
def root():
    """Redirect root URL to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")


@router.get("/health")
def health_check():
    """Return a public liveness signal without checking private services."""
    return {"status": "ok", "service": "miro-rag-api"}


@router.get("/api/v1/health", dependencies=[Depends(require_admin)])
def health_check_v1():
    """Check private dependencies for authenticated administrators."""
    from document_rag.vectorstore.chroma_manager import get_chroma_client
    from erp_data.odoo_connector import OdooConnector

    status = {"status": "ok", "services": {}}

    try:
        client = get_chroma_client()
        client.heartbeat()
        status["services"]["chroma"] = "ok"
    except Exception:
        logger.exception("Vectorstore health check failed.")
        status["services"]["chroma"] = "error"
        status["status"] = "degraded"

    try:
        connector = OdooConnector(technical=True)
        connector.authenticate(connector.username)
        status["services"]["odoo"] = "ok"
    except Exception:
        logger.exception("Odoo health check failed.")
        status["services"]["odoo"] = "error"
        status["status"] = "degraded"

    status["services"]["llm"] = "not checked"
    return status


@router.get("/api/v1/modules", response_model=ModuleCoverageResponse, dependencies=[Depends(get_current_user)])
def get_modules():
    """Get module coverage data comparing installed Odoo modules against AI capabilities."""
    from erp_data.odoo_connector import OdooConnector
    try:
        connector = OdooConnector(technical=True)
        uid = connector.authenticate(connector.username)
        records = connector.search_read(
            uid=uid,
            model="ir.module.module",
            domain=[("state", "=", "installed")],
            fields=["name"]
        )
        installed = {r["name"] for r in records}
    except Exception as exc:
        logger.exception("Odoo module coverage query failed.")
        statusCode, detail = public_error_details(exc)
        raise HTTPException(status_code=statusCode, detail=detail) from None

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


@router.get("/stats", response_model=StatsResponse, dependencies=[Depends(get_current_user)])
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
    except Exception as exc:
        logger.exception("Vectorstore statistics query failed.")
        statusCode, detail = public_error_details(exc)
        raise HTTPException(status_code=statusCode, detail=detail) from None
