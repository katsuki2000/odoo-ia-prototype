"""
tools/run_scalability_test.py

Scalability test for the document_rag ingestion pipeline. Duplicates the
document corpus `multiplier` times and measures total incremental-reindex time.

Recalibrated (todo/contexte.txt section 669/670) after 2 permanent, unrelated
decisions invalidated the original ~2500-chunk/code-duplication design:
- Section 363: fake_data/ removed, replaced by document_rag/documents/.
- Section 347-353: RAG scope permanently restricted to documents only, code
  ingestion removed (SUPPORTED_EXTENSIONS in incremental.py no longer includes
  .py) -- duplicating Odoo addon code no longer contributes any chunk, so it
  is no longer duplicated here.
Target: completes in < 6 minutes (< 360 seconds) on CPU.
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
from document_rag.ingestion.scan_root import DOCS_DIR
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

# document_rag/documents/ (config/settings.py::RAG_DOCS_PATH, .env-overridable) --
# same source of truth as the rest of the ingestion pipeline, not a private copy.
# ~27 chunks/copy measured directly (chunk_size=512) on the current 10-file,
# 140KB corpus (10 wiki/facture docs, including one scanned/OCR PDF).


def prepare_duplicated_corpus(target_dir: Path, multiplier: int = 22) -> list[Path]:
    """
    Duplicate the document corpus `multiplier` times into `target_dir` to
    generate enough chunks for benchmark testing.
    """
    docs_target = target_dir / "docs"
    docs_target.mkdir(parents=True, exist_ok=True)

    logger.info("Duplicating corpus %dx into %s...", multiplier, target_dir)

    for i in range(1, multiplier + 1):
        copy_docs = docs_target / f"copy_{i}"
        if DOCS_DIR.exists():
            shutil.copytree(DOCS_DIR, copy_docs, dirs_exist_ok=True)

    return [docs_target]


def run_scalability_benchmark(
    multiplier: int = 22,
    max_time_seconds: float = 360.0,
    min_chunks: int = 500,
    collection_name: str = "scalability_benchmark",
) -> dict[str, Any]:
    """Run the scalability benchmark and return performance metrics."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        corpus_roots = prepare_duplicated_corpus(temp_path / "corpus", multiplier=multiplier)
        db_path = temp_path / "chroma_benchmark"

        docs_manager = ChromaManager(db_path=db_path, collection_name=f"{collection_name}_docs")

        logger.info("Starting ingestion benchmark across %s...", corpus_roots)
        start_time = time.perf_counter()

        result = reindex_if_changed(
            roots=corpus_roots,
            docs_manager=docs_manager,
            code_manager=docs_manager,
            chunk_size=512,
            chunk_overlap=50,
        )

        elapsed_time = time.perf_counter() - start_time
        docs_stats = docs_manager.get_stats()
        total_chunks = int(docs_stats.get("total_chunks", 0) or 0)
        chunks_per_sec = total_chunks / elapsed_time if elapsed_time > 0 else 0.0

        metrics = {
            "multiplier": multiplier,
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
    parser.add_argument("--multiplier", type=int, default=22, help="Duplication multiplier (default: 22)")
    parser.add_argument("--max-time", type=float, default=360.0, help="Max allowed seconds (default: 360s)")
    parser.add_argument("--min-chunks", type=int, default=500, help="Minimum chunks required (default: 500)")
    args = parser.parse_args()

    metrics = run_scalability_benchmark(multiplier=args.multiplier, max_time_seconds=args.max_time, min_chunks=args.min_chunks)
    print("\n================= SCALABILITY BENCHMARK RESULTS =================")
    for key, val in metrics.items():
        if key != "result_summary":
            print(f"{key:28s}: {val}")
    print("=================================================================\n")

    return 0 if metrics["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

