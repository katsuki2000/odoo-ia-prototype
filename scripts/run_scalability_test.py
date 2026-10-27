"""
tools/run_scalability_test.py

Scalability test for the document_rag ingestion pipeline. Downloads the shared
Google Drive corpus once, duplicates it `multiplier` times locally and measures the
total incremental-reindex time (the download is measured separately).

The corpus lives in Google Drive (document_rag/documents/ is empty). Duplication has
to be local: through the Drive path the copies would share one source and one
revision and be skipped after the first. The expensive steps (OCR, chunking, embedding,
Chroma writes) are the same `_load_file` loaders as the production Drive ingestion.
Target: ingestion completes in < 6 minutes (< 360 seconds) on CPU.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Base paths and sys.path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from document_rag.ingestion.incremental import reindex_if_changed
from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)


class CorpusUnavailable(RuntimeError):
    """The Drive corpus cannot be used: not configured, not approved, no credentials or empty."""


def download_drive_corpus(target_dir: Path) -> dict[str, Any]:
    """Download the readable documents of the approved Drive folders once into target_dir."""
    from config.google_drive import GoogleDriveSettings
    from document_rag.ingestion.google_drive import GoogleDriveClient, document_suffix

    settings = GoogleDriveSettings.from_environment()
    if not settings.folderIds or not settings.approvedForRag:
        raise CorpusUnavailable(
            "Google Drive corpus not configured: GOOGLE_DRIVE_FOLDER_IDS and "
            "GOOGLE_DRIVE_APPROVED_FOR_RAG=true are required."
        )
    started = time.perf_counter()
    try:
        from google.auth.exceptions import DefaultCredentialsError
        try:
            client = GoogleDriveClient(timeout=settings.timeout, maxBytes=settings.maxBytes)
        except DefaultCredentialsError as error:
            raise CorpusUnavailable("Google Drive credentials are not available.") from error
    except ImportError as error:
        raise CorpusUnavailable("google-auth is not installed.") from error
    records = client.list_documents(settings.folderIds, maxFiles=settings.maxFiles)
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for record in records:
        suffix = document_suffix(record)
        if suffix is None:
            continue
        client.download(record, target_dir / f"{count:03d}{suffix}")
        count += 1
    if count == 0:
        raise CorpusUnavailable("The Drive corpus has no readable document.")
    return {"directory": target_dir, "files": count, "seconds": round(time.perf_counter() - started, 2)}


def prepare_duplicated_corpus(source_dir: Path, target_dir: Path, multiplier: int = 12) -> list[Path]:
    """
    Duplicate the documents of `source_dir` `multiplier` times into `target_dir` to
    generate enough chunks for benchmark testing. An empty source is refused: it would
    silently produce an empty benchmark.
    """
    if not any(path.is_file() for path in source_dir.rglob("*")):
        raise CorpusUnavailable(f"No document to duplicate in {source_dir}.")
    docs_target = target_dir / "docs"
    docs_target.mkdir(parents=True, exist_ok=True)

    logger.info("Duplicating corpus %dx into %s...", multiplier, target_dir)

    for i in range(1, multiplier + 1):
        shutil.copytree(source_dir, docs_target / f"copy_{i}", dirs_exist_ok=True)

    return [docs_target]


def run_scalability_benchmark(
    multiplier: int = 12,
    max_time_seconds: float = 360.0,
    min_chunks: int = 500,
    collection_name: str = "scalability_benchmark",
    source_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the scalability benchmark and return performance metrics.

    `source_dir` is a local corpus to duplicate; by default the Drive corpus is downloaded.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        if source_dir is None:
            downloaded = download_drive_corpus(temp_path / "drive_corpus")
            source_dir, source_files, download_seconds = downloaded["directory"], downloaded["files"], downloaded["seconds"]
        else:
            source_files = sum(1 for path in source_dir.rglob("*") if path.is_file())
            download_seconds = 0.0
        corpus_roots = prepare_duplicated_corpus(source_dir, temp_path / "corpus", multiplier=multiplier)
        db_path = temp_path / "chroma_benchmark"

        docs_manager = ChromaManager(db_path=db_path, collection_name=f"{collection_name}_docs")

        logger.info("Starting ingestion benchmark across %s...", corpus_roots)
        start_time = time.perf_counter()

        result = reindex_if_changed(
            roots=corpus_roots,
            docs_manager=docs_manager,
            chunk_size=RAG_CHUNK_SIZE,
            chunk_overlap=RAG_CHUNK_OVERLAP,
        )

        elapsed_time = time.perf_counter() - start_time
        docs_stats = docs_manager.get_stats()
        total_chunks = int(docs_stats.get("total_chunks", 0) or 0)
        chunks_per_sec = total_chunks / elapsed_time if elapsed_time > 0 else 0.0

        metrics = {
            "multiplier": multiplier,
            "source_files": source_files,
            "download_seconds": download_seconds,
            "elapsed_seconds": round(elapsed_time, 2),
            "total_chunks_indexed": total_chunks,
            "chunks_per_second": round(chunks_per_sec, 2),
            "min_chunks_required": min_chunks,
            "max_time_allowed_seconds": max_time_seconds,
            "success": (total_chunks >= min_chunks and elapsed_time <= max_time_seconds),
            "result_summary": result,
        }

        logger.info(
            "Benchmark completed in %.2fs. Total chunks indexed: %d (%.2f chunks/s). Success: %s",
            elapsed_time,
            total_chunks,
            chunks_per_sec,
            metrics["success"],
        )

        try:
            docs_manager.delete_collection()
            del docs_manager
        except Exception:
            pass

        return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Run document_rag Scalability Benchmark")
    parser.add_argument("--multiplier", type=int, default=12, help="Duplication multiplier (default: 12)")
    parser.add_argument("--max-time", type=float, default=360.0, help="Max allowed seconds (default: 360s)")
    parser.add_argument("--min-chunks", type=int, default=500, help="Minimum chunks required (default: 500)")
    args = parser.parse_args()

    try:
        metrics = run_scalability_benchmark(multiplier=args.multiplier, max_time_seconds=args.max_time, min_chunks=args.min_chunks)
    except CorpusUnavailable as error:
        print(f"Benchmark not run: {error}")
        return 2
    print("\n================= SCALABILITY BENCHMARK RESULTS =================")
    for key, val in metrics.items():
        if key != "result_summary":
            print(f"{key:28s}: {val}")
    print("=================================================================\n")

    return 0 if metrics["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

