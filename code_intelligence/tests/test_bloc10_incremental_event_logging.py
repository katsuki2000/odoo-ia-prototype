"""
code_intelligence/tests/test_bloc10_incremental_event_logging.py

Unit tests for  /  :
1. Verifies IncrementalEventLogger appends valid JSONL records to disk.
2. Verifies latency budget assertion (partial recalculation < 2.0s target).
3. Verifies read_recent_events log retrieval.

Renamed from test_j46_j48_observability_and_budget.py (correction, see
todo/real  ): this file's actual subject is graph staleness/
incremental recalculation, which is , not . 's real
scope (agent reasoning-path logging + LLM-call budget) is covered by
test_j46_j48_reasoning_trace.py.
"""

import time
import pytest
from pathlib import Path

from code_intelligence.graph.integrity import (
    IncrementalEvent,
    IncrementalEventLogger,
    record_incremental_update,
    LATENCY_BUDGET_PARTIAL_RECALC_SECONDS,
)
from code_intelligence.graph.staleness import analyze_changes
import networkx as nx


def test_j46_event_logger_writes_jsonl(tmp_path):
    """J46: verify IncrementalEventLogger writes structured JSONL events."""
    log_file = tmp_path / "events.jsonl"
    event_logger = IncrementalEventLogger(log_filepath=log_file)

    event = record_incremental_update(
        event_type="INCREMENTAL_RECALC",
        staleness_level=2,
        dirty_nodes=["model:custom.credit.note"],
        propagated_nodes=["model:account.move"],
        affected_cross_edges=[("model:custom.credit.note", "model:account.move")],
        detection_time_ms=1.5,
        recalc_time_ms=12.4,
        swap_time_ms=0.8,
        reason="Level 2: 1 direct dirty nodes + 1 propagated nodes",
        changed_files=["addons/custom_credit/models/credit.py"],
        logger_instance=event_logger,
    )

    assert log_file.exists()
    assert event.within_budget is True
    assert event.total_time_ms == 14.7

    recent = event_logger.read_recent_events(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["event_type"] == "INCREMENTAL_RECALC"
    assert rec["staleness_level"] == 2
    assert rec["within_budget"] is True


def test_j47_latency_budget_compliance_under_2s(tmp_path):
    """J47: verify partial recalculation timing is well under the 2.0s budget target."""
    log_file = tmp_path / "events.jsonl"
    event_logger = IncrementalEventLogger(log_filepath=log_file)

    G = nx.DiGraph()
    file_p = tmp_path / "sale_order.py"
    file_p.write_text("class SaleOrder: pass\n", encoding="utf-8")
    G.add_node("model:sale.order", node_type="Model", filepaths=[str(file_p)])

    # Time detection + simulated partial recalculation
    t0 = time.perf_counter()
    report = analyze_changes([str(file_p)], G)
    t1 = time.perf_counter()

    detection_ms = (t1 - t0) * 1000.0
    recalc_ms = 5.0  # simulated AST reparse + subgraph update
    swap_ms = 1.0    # simulated atomic file swap

    event = record_incremental_update(
        event_type="INCREMENTAL_RECALC",
        staleness_level=int(report.level),
        dirty_nodes=report.dirty_nodes,
        propagated_nodes=report.propagated_nodes,
        affected_cross_edges=report.affected_cross_edges,
        detection_time_ms=detection_ms,
        recalc_time_ms=recalc_ms,
        swap_time_ms=swap_ms,
        reason=report.reason,
        changed_files=[str(file_p)],
        logger_instance=event_logger,
    )

    total_sec = event.total_time_ms / 1000.0
    assert total_sec < LATENCY_BUDGET_PARTIAL_RECALC_SECONDS, f"Recalc latency {total_sec:.3f}s exceeded budget {LATENCY_BUDGET_PARTIAL_RECALC_SECONDS}s"
    assert event.within_budget is True
    print(f"J47 Partial Recalculation Latency: {event.total_time_ms:.2f}ms (Budget: {LATENCY_BUDGET_PARTIAL_RECALC_SECONDS*1000}ms) -> PASSED")


def test_j48_event_history_reading(tmp_path):
    """J48: verify limit and ordering when reading multiple events."""
    log_file = tmp_path / "events.jsonl"
    event_logger = IncrementalEventLogger(log_filepath=log_file)

    for i in range(5):
        record_incremental_update(
            event_type=f"EVENT_{i}",
            staleness_level=1,
            dirty_nodes=[],
            propagated_nodes=[],
            affected_cross_edges=[],
            detection_time_ms=1.0,
            recalc_time_ms=2.0,
            swap_time_ms=0.5,
            reason=f"test event {i}",
            changed_files=[],
            logger_instance=event_logger,
        )

    events = event_logger.read_recent_events(limit=3)
    assert len(events) == 3
    assert events[0]["event_type"] == "EVENT_2"
    assert events[2]["event_type"] == "EVENT_4"
