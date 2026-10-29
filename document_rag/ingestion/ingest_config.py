"""
document_rag/ingestion/ingest_config.py

Path configurations, module scopes, and logging setup for document ingestion.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys

from document_rag.ingestion.scan_root import DOCS_DIR

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "document_rag" / "ingestion" / "logs"

CORE_MODULES_ALWAYS_LOADED: list[str] = []


def setup_ingestion_logging() -> None:
    """Configure logging for ingestion runs."""
    LOGS_DIR.mkdir(exist_ok=True, parents=True)
    DOCS_DIR.mkdir(exist_ok=True, parents=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "ingestion.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


LOGS_DIR.mkdir(exist_ok=True, parents=True)
DOCS_DIR.mkdir(exist_ok=True, parents=True)
