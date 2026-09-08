"""
document_rag/ingestion/ingest_config.py

Path configurations, module scopes, and logging setup for document ingestion.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys

from config.settings import (
    CHROMA_PATH,
    CORE_ADDONS_PATH,
    CUSTOM_ADDONS_PATH,
    RAG_DOCS_PATH,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = Path(RAG_DOCS_PATH)
LOGS_DIR = PROJECT_ROOT / "document_rag" / "ingestion" / "logs"

CORE_ADDONS_ROOT = Path(CORE_ADDONS_PATH)
CUSTOM_ADDONS_ROOT = Path(CUSTOM_ADDONS_PATH)
CORE_MODULES_ALWAYS_LOADED = ["account", "sale", "stock"]


def documentary_code_module_dirs() -> list[Path]:
    """Real-corpus module directories this documentary RAG branch indexes."""
    if not CUSTOM_ADDONS_ROOT.exists():
        logger.warning(
            "CUSTOM_ADDONS_ROOT '%s' does not exist -- documentary code scope "
            "will be empty (no miro_ai, no custom_* modules).", CUSTOM_ADDONS_ROOT,
        )
        return []
    if not CORE_ADDONS_ROOT.exists():
        logger.warning(
            "CORE_ADDONS_ROOT '%s' does not exist -- core Odoo modules "
            "(account/sale/stock) and custom_* direct dependencies will be "
            "skipped in the documentary code scope.", CORE_ADDONS_ROOT,
        )

    from code_intelligence.utils import discover_odoo_modules
    from code_intelligence.extractor.manifest_parser import parse_manifest

    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(name: str, root: Path) -> None:
        if name in seen:
            return
        mod_dir = root / name
        if mod_dir.is_dir() and (mod_dir / "__manifest__.py").exists():
            dirs.append(mod_dir)
            seen.add(name)

    if CORE_ADDONS_ROOT.exists():
        for core_name in CORE_MODULES_ALWAYS_LOADED:
            _add(core_name, CORE_ADDONS_ROOT)
    _add("miro_ai", CUSTOM_ADDONS_ROOT)

    custom_modules = discover_odoo_modules(CUSTOM_ADDONS_ROOT, prefix="custom_")
    for mod_name in custom_modules:
        _add(mod_name, CUSTOM_ADDONS_ROOT)

    if CORE_ADDONS_ROOT.exists():
        for mod_name in custom_modules:
            manifest_p = CUSTOM_ADDONS_ROOT / mod_name / "__manifest__.py"
            try:
                manifest = parse_manifest(manifest_p)
            except Exception as e:
                logger.error("Documentary scope: failed to parse manifest for '%s': %s", mod_name, e)
                continue
            for dep_name in manifest.depends:
                _add(dep_name, CORE_ADDONS_ROOT)

    return dirs


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

CODE_DIRS: list[Path] = documentary_code_module_dirs()
CODE_DIR = None
