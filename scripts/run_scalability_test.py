"""
tools/run_scalability_test.py

Scalability test for Step 5b Day 4.
Duplicates fake_data content 5x (~2500+ chunks), runs ingestion, and measures total time.
Target: completes in < 5 minutes (< 300 seconds) on CPU.
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
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FAKE_DATA_DIR = PROJECT_ROOT / "document_rag/fake_data"
DOCS_DIR = FAKE_DATA_DIR / "documents"
from config.settings import CORE_ADDONS_PATH
ODOO_ADDONS_DIR = Path(CORE_ADDONS_PATH)
CODE_DIR = ODOO_ADDONS_DIR if ODOO_ADDONS_DIR.exists() else (FAKE_DATA_DIR / "code")


def prepare_duplicated_corpus(target_dir: Path, multiplier: int = 5) -> list[Path]:
    """
    Duplicate documents and code subsets `multiplier` times into `target_dir`
    to generate ~2500+ chunks for benchmark testing.
    """
    docs_target = target_dir / "docs"
    code_target = target_dir / "code"
    docs_target.mkdir(parents=True, exist_ok=True)
    code_target.mkdir(parents=True, exist_ok=True)

    logger.info("Duplicating corpus %dx into %s...", multiplier, target_dir)

    for i in range(1, multiplier + 1):
        # Copy docs
        copy_docs = docs_target / f"copy_{i}"
        if DOCS_DIR.exists():
            shutil.copytree(DOCS_DIR, copy_docs, dirs_exist_ok=True)

        # Copy sale module code (~650 chunks per copy -> 5 * 650 + docs = ~3400 chunks)
        sale_src = CODE_DIR / "sale"
        if sale_src.exists():
            copy_sale = code_target / f"copy_{i}" / "sale"
            shutil.copytree(sale_src, copy_sale, dirs_exist_ok=True)
        else:
            # Fallback if sale subdir structured differently
            copy_code = code_target / f"copy_{i}"
            shutil.copytree(CODE_DIR, copy_code, dirs_exist_ok=True)

    return [docs_target, code_target]


def run_scalability_benchmark(
    multiplier: int = 5,
    max_time_seconds: float = 300.0,
    collection_name: str = "scalability_benchmark",
) -> dict[str, Any]:
    """Run the scalability benchmark and return performance metrics."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        corpus_roots = prepare_duplicated_corpus(temp_path / "corpus", multiplier=multiplier)
        db_path = temp_path / "chroma_benchmark"

        docs_manager = ChromaManager(db_path=db_path, collection_name=f"{collection_name}_docs")
        code_manager = ChromaManager(db_path=db_path, collection_name=f"{collection_name}_code")

        logger.info("Starting ingestion benchmark across %s...", corpus_roots)
        start_time = time.perf_counter()

        result = reindex_if_changed(
            roots=corpus_roots,
            docs_manager=docs_manager,
            code_manager=code_manager,
            chunk_size=512,
            chunk_overlap=50,
        )

        elapsed_time = time.perf_counter() - start_time
        docs_stats = docs_manager.get_stats()
        code_stats = code_manager.get_stats()
        total_chunks = int(docs_stats.get("total_chunks", 0) or 0) + int(code_stats.get("total_chunks", 0) or 0)
        chunks_per_sec = total_chunks / elapsed_time if elapsed_time > 0 else 0.0

        metrics = {
            "multiplier": multiplier,
            "elapsed_seconds": round(elapsed_time, 2),
            "total_chunks_indexed": total_chunks,
            "chunks_per_second": round(chunks_per_sec, 2),
            "max_time_allowed_seconds": max_time_seconds,
            "success": (total_chunks >= 2500 and elapsed_time <= max_time_seconds),
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
            code_manager.delete_collection()
            del docs_manager, code_manager
        except Exception:
            pass

        return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Step 5b Day 4 Scalability Benchmark")
    parser.add_argument("--multiplier", type=int, default=5, help="Duplication multiplier (default: 5)")
    parser.add_argument("--max-time", type=float, default=300.0, help="Max allowed seconds (default: 300s)")
    args = parser.parse_args()

    metrics = run_scalability_benchmark(multiplier=args.multiplier, max_time_seconds=args.max_time)
    print("\n================= SCALABILITY BENCHMARK RESULTS =================")
    for key, val in metrics.items():
        if key != "result_summary":
            print(f"{key:28s}: {val}")
    print("=================================================================\n")

    return 0 if metrics["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
