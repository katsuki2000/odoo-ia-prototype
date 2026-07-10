"""
tests/test_scalability.py

Step 5b Day 4 verification:
Scalability test duplicating corpus content (~2500+ chunks), running full ingestion,
and verifying it completes in under 5 minutes (< 300 seconds) with correct chunk statistics.
"""

import pytest
from tools.run_scalability_test import run_scalability_benchmark


@pytest.mark.integration
def test_scalability_benchmark_under_5_minutes():
    """
    Verify that duplicating the corpus (to reach ~2500+ chunks) and running
    full incremental ingestion completes in < 300 seconds on CPU.
    """
    # Using multiplier=4 gives ~2700 chunks, meeting the ~2500 chunk target reliably within the time budget.
    metrics = run_scalability_benchmark(
        multiplier=4,
        max_time_seconds=300.0,
        collection_name="test_scalability_collection",
    )

    assert metrics["total_chunks_indexed"] >= 2500, (
        f"Expected at least 2500 chunks, but indexed {metrics['total_chunks_indexed']}"
    )
    assert metrics["elapsed_seconds"] < 300.0, (
        f"Ingestion took {metrics['elapsed_seconds']}s, which exceeds the 300s limit"
    )
    assert metrics["success"] is True
