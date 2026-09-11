"""
tests/test_scalability.py
Scalability test duplicating the document corpus, running full ingestion,
and verifying it completes in under 6 minutes (< 360 seconds) with correct chunk statistics.
"""

import pytest
from scripts.run_scalability_test import run_scalability_benchmark


@pytest.mark.integration
def test_scalability_benchmark_under_6_minutes():
    """
    Verify that duplicating the document corpus and running full incremental
    ingestion completes in < 360 seconds on CPU.

    Recalibrated (todo/contexte.txt section 669/670): the original ~2500-chunk
    target assumed duplicating Odoo addon code (.py) alongside documents --
    invalidated by the permanent RAG-scope restriction to documents only
    (section 347-353, SUPPORTED_EXTENSIONS in incremental.py no longer includes
    .py). document_rag/documents/ (10 files, 140KB, incl. one scanned/OCR PDF)
    measures ~27 chunks/copy at chunk_size=512. multiplier=22 gives ~594 chunks
    (measured: 270 chunks at multiplier=10 -- exact 27/copy) -- ~19% margin over
    the 500-chunk target. Timing measured directly (not estimated): 10 copies
    (270 chunks, OCR included) took 139.21s (13.92s/copy) -> 22 copies
    extrapolate to ~306s, leaving a comfortable margin under the 360s budget.
    """
    metrics = run_scalability_benchmark(
        multiplier=22,
        max_time_seconds=360.0,
        min_chunks=500,
        collection_name="test_scalability_collection",
    )

    assert metrics["total_chunks_indexed"] >= 500, (
        f"Expected at least 500 chunks, but indexed {metrics['total_chunks_indexed']}"
    )
    assert metrics["elapsed_seconds"] < 360.0, (
        f"Ingestion took {metrics['elapsed_seconds']}s, which exceeds the 360s limit"
    )
    assert metrics["success"] is True

