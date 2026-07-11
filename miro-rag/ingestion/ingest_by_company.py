"""
Per-company ingestion script for multi-tenant Qdrant setup.

Ingests documents from fake_data/company_alpha/ and fake_data/company_beta/
into their respective Qdrant collections.  Uses the same loaders as
ingest_all.py but routes each company's files to its own collection.

Usage:
    # Ingest all companies
    python -m ingestion.ingest_by_company

    # Ingest one company only
    python -m ingestion.ingest_by_company --company company_alpha

    # Dry-run: print file counts without embedding
    python -m ingestion.ingest_by_company --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

from ingestion.code_loader import load_python_directory, load_xml_directory
from ingestion.pdf_loader import load_pdf_directory
from ingestion.wiki_loader import load_wiki_directory
from vectorstore.company_collections import (
    get_manager_for_collection,
    get_company_docs_dirs,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FAKE_DATA_ROOT = PROJECT_ROOT / "fake_data"

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50


# ---------------------------------------------------------------------------
# Per-company ingestion
# ---------------------------------------------------------------------------

def ingest_company(
    collection_name: str,
    dirs: list[Path],
    *,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Ingest all supported documents from *dirs* into the Qdrant collection
    identified by *collection_name*.

    Args:
        collection_name: Target Qdrant collection (e.g. "company_alpha").
        dirs: List of directories to scan (docs/ and/or code/ sub-dirs).
        chunk_size: Token chunk size passed to loaders.
        chunk_overlap: Overlap between consecutive chunks.
        dry_run: When True, enumerate files but skip embedding.

    Returns:
        Summary dict with per-type counts and total elapsed time.
    """
    manager = get_manager_for_collection(collection_name)
    start = time.time()

    stats: dict[str, int] = {
        "doc_pdf": 0,
        "doc_wiki": 0,
        "code_python": 0,
        "code_xml": 0,
        "total_chunks": 0,
    }

    for directory in dirs:
        if not directory.exists():
            logger.warning("Directory does not exist, skipping: %s", directory)
            continue

        dir_name = directory.name  # "docs" or "code"

        if dir_name == "docs":
            # --- PDFs ---
            pdf_docs = load_pdf_directory(
                directory,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            pdf_chunks = [c for doc in pdf_docs for c in doc["chunks"]]
            pdf_metas = [m for doc in pdf_docs for m in doc["metadatas"]]
            if pdf_chunks:
                logger.info(
                    "[%s] Found %d PDF chunks in %s",
                    collection_name, len(pdf_chunks), directory,
                )
                if not dry_run:
                    manager.add_chunks(pdf_chunks, pdf_metas)
                stats["doc_pdf"] += len(pdf_chunks)
                stats["total_chunks"] += len(pdf_chunks)

            # --- Wiki / text / markdown ---
            wiki_docs = load_wiki_directory(
                directory,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            wiki_chunks = [c for doc in wiki_docs for c in doc["chunks"]]
            wiki_metas = [m for doc in wiki_docs for m in doc["metadatas"]]
            if wiki_chunks:
                logger.info(
                    "[%s] Found %d wiki chunks in %s",
                    collection_name, len(wiki_chunks), directory,
                )
                if not dry_run:
                    manager.add_chunks(wiki_chunks, wiki_metas)
                stats["doc_wiki"] += len(wiki_chunks)
                stats["total_chunks"] += len(wiki_chunks)

        elif dir_name == "code":
            # --- Python ---
            py_docs = load_python_directory(
                directory,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            py_chunks = [c for doc in py_docs for c in doc["chunks"]]
            py_metas = [m for doc in py_docs for m in doc["metadatas"]]
            if py_chunks:
                logger.info(
                    "[%s] Found %d Python chunks in %s",
                    collection_name, len(py_chunks), directory,
                )
                if not dry_run:
                    manager.add_chunks(py_chunks, py_metas)
                stats["code_python"] += len(py_chunks)
                stats["total_chunks"] += len(py_chunks)

            # --- XML ---
            xml_docs = load_xml_directory(
                directory,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            xml_chunks = [c for doc in xml_docs for c in doc["chunks"]]
            xml_metas = [m for doc in xml_docs for m in doc["metadatas"]]
            if xml_chunks:
                logger.info(
                    "[%s] Found %d XML chunks in %s",
                    collection_name, len(xml_chunks), directory,
                )
                if not dry_run:
                    manager.add_chunks(xml_chunks, xml_metas)
                stats["code_xml"] += len(xml_chunks)
                stats["total_chunks"] += len(xml_chunks)

        else:
            logger.debug(
                "[%s] Unknown sub-directory name '%s', skipping: %s",
                collection_name, dir_name, directory,
            )

    elapsed = round(time.time() - start, 2)
    stats["elapsed_seconds"] = elapsed  # type: ignore[assignment]

    mode = "DRY-RUN" if dry_run else "INGESTED"
    logger.info(
        "[%s] %s — %d total chunks in %.2fs "
        "(pdf=%d, wiki=%d, py=%d, xml=%d)",
        collection_name,
        mode,
        stats["total_chunks"],
        elapsed,
        stats["doc_pdf"],
        stats["doc_wiki"],
        stats["code_python"],
        stats["code_xml"],
    )

    # Print live stats from Qdrant after ingestion
    if not dry_run:
        try:
            qdrant_stats = manager.get_stats()
            logger.info("[%s] Qdrant stats: %s", collection_name, qdrant_stats)
        except Exception as exc:
            logger.warning("[%s] Could not fetch Qdrant stats: %s", collection_name, exc)

    return stats


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def ingest_all_companies(
    *,
    only: str | None = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    dry_run: bool = False,
    fake_data_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Ingest documents for every configured company (or a single one).

    Args:
        only: If set, restrict ingestion to this collection name.
        chunk_size: Token chunk size.
        chunk_overlap: Chunk overlap.
        dry_run: Enumerate without embedding.
        fake_data_root: Override default fake_data directory.

    Returns:
        Mapping of collection_name → per-company stats dict.
    """
    company_dirs = get_company_docs_dirs(fake_data_root)

    if not company_dirs:
        logger.error(
            "No company directories found under %s. "
            "Expected fake_data/company_alpha/ and fake_data/company_beta/.",
            fake_data_root or FAKE_DATA_ROOT,
        )
        return {}

    results: dict[str, dict[str, Any]] = {}

    for collection_name, dirs in sorted(company_dirs.items()):
        if only and collection_name != only:
            logger.info("Skipping collection '%s' (--company filter)", collection_name)
            continue

        logger.info(
            "=== Ingesting collection '%s' from %d dir(s) ===",
            collection_name, len(dirs),
        )
        results[collection_name] = ingest_company(
            collection_name,
            dirs,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            dry_run=dry_run,
        )

    # Summary
    grand_total = sum(v.get("total_chunks", 0) for v in results.values())
    logger.info(
        "=== Re-ingestion complete: %d collection(s), %d total chunks ===",
        len(results), grand_total,
    )
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-ingest all company documents into their Qdrant collections."
    )
    parser.add_argument(
        "--company",
        default=None,
        help="Restrict to a single collection name (e.g. company_alpha).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Token chunk size (default: {CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=CHUNK_OVERLAP,
        help=f"Chunk overlap (default: {CHUNK_OVERLAP}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count files/chunks without embedding or upserting.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    results = ingest_all_companies(
        only=args.company,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        dry_run=args.dry_run,
    )

    if not results:
        logger.error("No collections were ingested.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
