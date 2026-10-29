"""System and health check endpoints."""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from api.auth import require_admin
from config.settings import ODOO_DB

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
    from document_rag.vectorstore.chroma_manager import ChromaManager
    from erp_data.odoo_connector import OdooConnector

    status = {"status": "ok", "services": {}}

    try:
        manager = ChromaManager()
        manager.client.heartbeat()
        status["services"]["chroma"] = "ok"
    except Exception:
        logger.exception("Vectorstore health check failed.")
        status["services"]["chroma"] = "error"
        status["status"] = "degraded"

    try:
        connector = OdooConnector(db=ODOO_DB, technical=True)
        connector.authenticate(connector.username)
        status["services"]["odoo"] = "ok"
    except Exception:
        logger.exception("Odoo health check failed.")
        status["services"]["odoo"] = "error"
        status["status"] = "degraded"

    status["services"]["llm"] = "not checked"
    return status
