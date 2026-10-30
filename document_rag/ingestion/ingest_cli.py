"""Command-line entry point for documentary ingestion."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from config.settings import CHROMA_PATH, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.ingestion.logging_utils import LOGS_DIR
from document_rag.ingestion.scan_root import DOCS_DIR

logger = logging.getLogger(__name__)


def main() -> int:
    from document_rag.ingestion.ingest_all import IngestionOrchestrator

    parser = argparse.ArgumentParser(description="Ingest documents into ChromaDB")
    parser.add_argument("--clear", action="store_true", help="Replace the collection before ingestion")
    parser.add_argument("--docs-dir", default=str(DOCS_DIR), help="Document directory; pass an empty string to skip")
    parser.add_argument("--db-path", type=Path, default=CHROMA_PATH, help="ChromaDB storage directory")
    parser.add_argument("--chunk-size", type=int, default=RAG_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=RAG_CHUNK_OVERLAP)
    args = parser.parse_args()

    orchestrator = IngestionOrchestrator(
        chroma_db_path=args.db_path,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    result = (
        orchestrator.clear_and_reingest(args.docs_dir)
        if args.clear
        else orchestrator.ingest_all(args.docs_dir)
    )

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stats_file = LOGS_DIR / "ingestion_stats.json"
    stats_file.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    logger.info("Statistics saved to %s", stats_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
