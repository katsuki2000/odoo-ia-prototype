"""
Multi-tenant Qdrant collection routing by Odoo company_id.

Each company gets its own Qdrant collection (company_alpha, company_beta).
The retrieval pipeline selects the collection from the authenticated user's
company_id before running vector or BM25 search.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config.settings import COMPANY_COLLECTIONS, VECTOR_BACKEND

if TYPE_CHECKING:
    from vectorstore.search import BM25Index

logger = logging.getLogger(__name__)

_manager_cache: dict[str, object] = {}
_bm25_cache: dict[str, object] = {}


def collection_name_for_company(company_id: int) -> str:
    """Resolve the Qdrant collection name for an Odoo company_id."""
    collection = COMPANY_COLLECTIONS.get(company_id)
    if collection:
        return collection

    raise ValueError(
        f"No vector collection configured for company_id={company_id}. "
        f"Known companies: {list(COMPANY_COLLECTIONS.keys())}"
    )


def get_company_manager(company_id: int, *, url: str | None = None, client=None):
    """
    Return a QdrantManager scoped to the given company.

    Managers are cached per collection name for reuse across requests.
    """
    from vectorstore.qdrant_manager import QdrantManager

    collection_name = collection_name_for_company(company_id)
    if collection_name not in _manager_cache:
        kwargs = {"collection_name": collection_name}
        if client is not None:
            kwargs["client"] = client
        elif url is not None:
            kwargs["url"] = url
        _manager_cache[collection_name] = QdrantManager(**kwargs)

    return _manager_cache[collection_name]


def get_company_retriever(
    company_id: int,
    *,
    url: str | None = None,
    client=None,
) -> tuple[object, BM25Index]:
    """
    Return (vector_manager, bm25_index) for the given company_id.

    Builds the BM25 index from the company-scoped collection on first access.
    """
    from vectorstore.search import BM25Index

    collection_name = collection_name_for_company(company_id)
    manager = get_company_manager(company_id, url=url, client=client)

    if collection_name not in _bm25_cache:
        bm25 = BM25Index()
        bm25.build_from_chroma(manager)
        _bm25_cache[collection_name] = bm25
    else:
        bm25 = _bm25_cache[collection_name]
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
