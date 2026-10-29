"""System and health check endpoints."""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from api.auth import require_admin
from config.settings import ODOO_DB

logger = logging.getLogger(__name__)
router = APIRouter()


def _probe(status: dict, service: str, check: Callable[[], object]) -> None:
    try:
        check()
        status["services"][service] = "ok"
    except Exception:
        logger.exception("%s health check failed.", service)
        status["services"][service] = "error"
        status["status"] = "degraded"


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

    def check_odoo():
        connector = OdooConnector(db=ODOO_DB, technical=True)
        connector.authenticate(connector.username)

    status = {"status": "ok", "services": {}}
    _probe(status, "chroma", lambda: ChromaManager().client.heartbeat())
    _probe(status, "odoo", check_odoo)
    status["services"]["llm"] = "not checked"
    return status
