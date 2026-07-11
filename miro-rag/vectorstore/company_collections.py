"""
Multi-tenant Qdrant collection routing by Odoo company_id.

Each company gets its own Qdrant collection (company_alpha, company_beta).
The retrieval pipeline selects the collection from the authenticated user's
company_id before running vector or BM25 search.

Folder convention for ingestion:
    fake_data/company_alpha/docs/   → collection "company_alpha"
    fake_data/company_alpha/code/   → collection "company_alpha"
    fake_data/company_beta/docs/    → collection "company_beta"
    fake_data/company_beta/code/    → collection "company_beta"
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from config.settings import COMPANY_COLLECTIONS, COMPANY_FOLDERS, VECTOR_BACKEND

if TYPE_CHECKING:
    from vectorstore.search import BM25Index

logger = logging.getLogger(__name__)

_manager_cache: dict[str, object] = {}
_bm25_cache: dict[str, object] = {}

# Root of the miro-rag project (parent of this file's package)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Company-id → collection name resolution
# ---------------------------------------------------------------------------

def collection_name_for_company(company_id: int) -> str:
    """Resolve the Qdrant collection name for an Odoo company_id."""
    collection = COMPANY_COLLECTIONS.get(company_id)
    if collection:
        return collection

    raise ValueError(
        f"No vector collection configured for company_id={company_id}. "
        f"Known companies: {list(COMPANY_COLLECTIONS.keys())}"
    )


# ---------------------------------------------------------------------------
# File-path → collection name resolution (used by watcher + ingest scripts)
# ---------------------------------------------------------------------------

def collection_for_path(file_path: str | Path) -> str | None:
    """
    Derive the Qdrant collection name from a file's location inside fake_data/.

    Returns the collection name string when the path sits under a recognised
    company sub-folder (e.g. ``fake_data/company_alpha/docs/``), or ``None``
    when the file does not belong to any configured company.

    Examples::

        collection_for_path(".../fake_data/company_alpha/docs/wiki.txt")
        # → "company_alpha"

        collection_for_path(".../fake_data/documents/wiki.txt")
        # → None   (legacy flat layout — caller decides how to handle)
    """
    path = Path(file_path).resolve()
    parts = path.parts

    for idx, part in enumerate(parts):
        if part in COMPANY_FOLDERS:
            collection_name = COMPANY_FOLDERS[part]
            logger.debug(
                "Path '%s' resolved to collection '%s'", file_path, collection_name
            )
            return collection_name

    logger.debug(
        "Path '%s' does not match any company folder — returning None", file_path
    )
    return None


def get_company_docs_dirs(
    fake_data_root: str | Path | None = None,
) -> dict[str, list[Path]]:
    """
    Return a mapping of collection_name → list of watch directories.

    The directories are the ``docs/`` and ``code/`` subdirectories under each
    company folder inside ``fake_data/``.  Only directories that actually exist
    are included, so the watcher won't crash on a missing path.

    Args:
        fake_data_root: Override the default ``<project_root>/fake_data`` root.

    Returns:
        Example::

            {
                "company_alpha": [
                    PosixPath(".../fake_data/company_alpha/docs"),
                    PosixPath(".../fake_data/company_alpha/code"),
                ],
                "company_beta": [
                    PosixPath(".../fake_data/company_beta/docs"),
                ],
            }
    """
    root = Path(fake_data_root).resolve() if fake_data_root else _PROJECT_ROOT / "fake_data"
    result: dict[str, list[Path]] = {}

    for collection_name, folder_name in COMPANY_FOLDERS.items():
        paths: list[Path] = []
        for sub in ("docs", "code"):
            candidate = root / folder_name / sub
            if candidate.exists():
                paths.append(candidate)
            else:
                logger.debug(
                    "Company dir not found (skipping): %s", candidate
                )
        if paths:
            result[collection_name] = paths

    return result


# ---------------------------------------------------------------------------
# Manager / BM25 cache
# ---------------------------------------------------------------------------

def get_company_manager(
    company_id: int, *, url: str | None = None, client=None, embedding_model: str | None = None
):
    """
    Return a QdrantManager initialized for the given company's collection.

    Managers are cached per collection name for reuse across requests.
    """
    from vectorstore.qdrant_manager import QdrantManager

    collection_name = collection_name_for_company(company_id)
    cache_key = f"{collection_name}_{embedding_model or 'default'}"
    if cache_key not in _manager_cache:
        kwargs: dict = {"collection_name": collection_name}
        if client is not None:
            kwargs["client"] = client
        elif url is not None:
            kwargs["url"] = url
        if embedding_model is not None:
            kwargs["embedding_model"] = embedding_model
        _manager_cache[cache_key] = QdrantManager(**kwargs)

    return _manager_cache[cache_key]


def get_manager_for_collection(
    collection_name: str, *, url: str | None = None, client=None, embedding_model: str | None = None
):
    """
    Return a QdrantManager for a named collection (used by watcher/ingest).

    Unlike ``get_company_manager`` this accepts the collection name directly,
    which is more natural when the caller resolved the name from a file path.
    """
    from vectorstore.qdrant_manager import QdrantManager

    cache_key = f"{collection_name}_{embedding_model or 'default'}"
    if cache_key not in _manager_cache:
        kwargs: dict = {"collection_name": collection_name}
        if client is not None:
            kwargs["client"] = client
        elif url is not None:
            kwargs["url"] = url
        if embedding_model is not None:
            kwargs["embedding_model"] = embedding_model
        _manager_cache[cache_key] = QdrantManager(**kwargs)

    return _manager_cache[cache_key]


def get_company_retriever(
    company_id: int,
    *,
    url: str | None = None,
    client=None,
    embedding_model: str | None = None,
) -> tuple[object, BM25Index]:
    """
    Return (vector_manager, bm25_index) for the given company_id.

    Builds the BM25 index from the company-scoped collection on first access.
    """
    from vectorstore.search import BM25Index

    collection_name = collection_name_for_company(company_id)
    cache_key = f"{collection_name}_{embedding_model or 'default'}"
    manager = get_company_manager(company_id, url=url, client=client, embedding_model=embedding_model)

    if cache_key not in _bm25_cache:
        bm25 = BM25Index()
        bm25.build_from_chroma(manager)
        _bm25_cache[cache_key] = bm25
    else:
        bm25 = _bm25_cache[cache_key]
        if not bm25.is_built:
            bm25.build_from_chroma(manager)

    return manager, bm25


def ensure_company_collections(company_ids: list[int] | None = None) -> list[str]:
    """
    Ensure Qdrant collections exist for the configured companies.

    Returns the list of collection names that were initialized.
    """
    if VECTOR_BACKEND != "qdrant":
        return []

    ids = company_ids if company_ids is not None else list(COMPANY_COLLECTIONS.keys())
    created: list[str] = []

    for company_id in ids:
        try:
            manager = get_company_manager(company_id)
            created.append(manager.collection_name)
        except ValueError as exc:
            logger.error("Skipping company collection init: %s", exc)

    logger.info("Company Qdrant collections ready: %s", created)
    return created


def clear_retriever_cache() -> None:
    """Reset cached managers and BM25 indexes (used in tests)."""
    _manager_cache.clear()
    _bm25_cache.clear()
