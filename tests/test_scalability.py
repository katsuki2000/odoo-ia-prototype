"""
tests/test_scalability.py
Scalability test duplicating the document corpus, running full ingestion,
and verifying it completes in under 6 minutes (< 360 seconds) with correct chunk statistics.
"""

import pytest
from scripts.run_scalability_test import CorpusUnavailable, run_scalability_benchmark


@pytest.mark.integration
def test_scalability_benchmark_under_6_minutes():
    """
    Verify that downloading the Google Drive corpus once, duplicating it locally and
    running full incremental ingestion completes in < 360 seconds on CPU (the download
    is measured separately and excluded from the budget).

    The corpus is no longer in document_rag/documents/ (it lives in Drive), so the test
    is skipped when the Drive corpus is not configured or not reachable.

    Calibration (todo/contexte.txt section 1598, measured 27/10/2026 on the 18-file Drive
    corpus, 1 copy): 45 chunks and 25.0 s per copy (OCR included; download 31 s, excluded).
    multiplier=12 gives 540 chunks (>= 500, 8% margin) and ~300 s extrapolated linearly
    (360 s budget, ~17% margin). The previous multiplier of 22 would give ~990 chunks in
    ~550 s, above the budget. The linear extrapolation is an assumption until the full
    12-copy run has been measured.
    """
    try:
        metrics = run_scalability_benchmark(
            multiplier=12,
            max_time_seconds=360.0,
            min_chunks=500,
            collection_name="test_scalability_collection",
        )
    except CorpusUnavailable as error:
        pytest.skip(str(error))

    assert metrics["total_chunks_indexed"] >= 500, (
        f"Expected at least 500 chunks, but indexed {metrics['total_chunks_indexed']}"
    )
    assert metrics["elapsed_seconds"] < 360.0, (
        f"Ingestion took {metrics['elapsed_seconds']}s, which exceeds the 360s limit"
    )
    assert metrics["success"] is True

