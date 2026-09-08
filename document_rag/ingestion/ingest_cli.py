"""
document_rag/ingestion/ingest_cli.py

CLI entry point for document and code ingestion into ChromaDB.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from config.settings import CHROMA_PATH
from document_rag.ingestion.ingest_config import DOCS_DIR, LOGS_DIR

logger = logging.getLogger(__name__)


def main() -> int:
    """Main entry point for ingestion CLI."""
    from document_rag.ingestion.ingest_all import IngestionOrchestrator

    parser = argparse.ArgumentParser(
        description="Ingest all documents into ChromaDB"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear collection before ingesting",
    )
    parser.add_argument(
        "--docs-dir",
        type=str,
        default=DOCS_DIR,
        help="Path to documents directory. Pass '' to skip docs.",
    )
    parser.add_argument(
        "--code-dir",
        type=str,
        default="",
        help="Path to code directory to ingest. Empty by default ('').",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=CHROMA_PATH,
        help="Path to ChromaDB storage",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="Chunk size for text splitting",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=50,
        help="Overlap between chunks",
    )

    args = parser.parse_args()

    orchestrator = IngestionOrchestrator(
        chroma_db_path=args.db_path,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    if args.clear:
        stats = orchestrator.clear_and_reingest(
            docs_dir=args.docs_dir,
            code_dir=args.code_dir,
        )
    else:
        stats = orchestrator.ingest_all(
            docs_dir=args.docs_dir,
            code_dir=args.code_dir,
        )

    stats_file = LOGS_DIR / "ingestion_stats.json"
    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2, default=str)

    logger.info(f"\nStatistics saved to {stats_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
