"""
code_intelligence/tests/test_j37_j42_staleness_and_atomic_swap.py

Unit & Concurrency Tests for  /  :
- J37: Level 1 File-only staleness detector.
- J38: Level 2 Dependency edge propagation (EXTENDS, RESTRICTED_BY, HAS_FIELD).
- J39: Level 3 Uncovered dynamic pattern detection (getattr, safe_eval, eval, manifest, ACL) + staleness_reason.
- J40: Atomic graph swap (fsync + os.replace).
- J41: Graph versioning & git commit metadata.
- J42: 20 concurrent readers + 1 writer atomic swap stress test.
"""

import os
import json
import time
import threading
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
import networkx as nx

from code_intelligence.graph.staleness_detector import (
    StalenessLevel,
    StalenessReport,
    analyze_changes,
    get_nodes_for_filepath,
    propagate_dirty_nodes,
)
from code_intelligence.graph import (
    atomic_write_json,
    atomic_read_json,
    serialize_graph_with_metadata,
    deserialize_graph_with_metadata,
    get_git_commit_hash,
)


@pytest.fixture
def sample_graph():
    """Build a sample NetworkX DiGraph for staleness tests."""
    G = nx.DiGraph()
    # Nodes
    G.add_node("model:account.move", node_type="Model", filepaths=["/path/to/account_move.py"])
    G.add_node("model:custom.credit.note", node_type="Model", filepaths=["/path/to/custom_credit.py"])
    G.add_node("rule:rule_account_move", node_type="Rule", filepath="/path/to/security.xml")

    # Edges
    G.add_edge("model:custom.credit.note", "model:account.move", edge_type="EXTENDS")
    G.add_edge("model:account.move", "rule:rule_account_move", edge_type="RESTRICTED_BY")

    return G


def test_j37_level1_file_only_staleness(sample_graph, tmp_path):
    """J37: verify Level 1 file-only dirty node resolution when no dependent edges exist."""
    file_p = tmp_path / "standalone_doc.py"
    file_p.write_text("class StandaloneDoc:\n    pass\n", encoding="utf-8")

    sample_graph.add_node("model:standalone.doc", node_type="Model", filepaths=[str(file_p)])

    report = analyze_changes([str(file_p)], sample_graph)

    assert report.level == StalenessLevel.FILE_ONLY
    assert "model:standalone.doc" in report.dirty_nodes
    assert len(report.propagated_nodes) == 0
    assert report.reason.startswith("Level 1")


def test_j38_level2_edge_propagation_staleness(sample_graph, tmp_path):
    """J38: verify Level 2 dependency edge propagation."""
    file_p = tmp_path / "account_move.py"
    file_p.write_text("class AccountMove:\n    pass\n", encoding="utf-8")

    sample_graph.nodes["model:account.move"]["filepaths"] = [str(file_p)]

    report = analyze_changes([str(file_p)], sample_graph)

    assert report.level == StalenessLevel.PROPAGATION
    assert "model:account.move" in report.dirty_nodes
    assert "model:custom.credit.note" in report.propagated_nodes or "rule:rule_account_move" in report.propagated_nodes
    assert "Level 2" in report.reason


def test_j39_level3_manifest_change_rebuild(sample_graph, tmp_path):
    """J39: manifest file change triggers Level 3 FULL_REBUILD."""
    manifest_p = tmp_path / "__manifest__.py"
    manifest_p.write_text("{'name': 'Test'}\n", encoding="utf-8")

    report = analyze_changes([str(manifest_p)], sample_graph)

    assert report.level == StalenessLevel.FULL_REBUILD
    assert report.requires_full_rebuild is True
    assert "manifest file changed" in report.reason


def test_j39_level3_acl_csv_change_rebuild(sample_graph, tmp_path):
    """J39: ir.model.access.csv change triggers Level 3 FULL_REBUILD."""
    csv_p = tmp_path / "ir.model.access.csv"
    csv_p.write_text("id,name,model_id\n", encoding="utf-8")

    report = analyze_changes([str(csv_p)], sample_graph)

    assert report.level == StalenessLevel.FULL_REBUILD
    assert report.requires_full_rebuild is True
    assert "global access control CSV changed" in report.reason


def test_j39_level3_dynamic_getattr_rebuild(sample_graph, tmp_path):
    """J39: dynamic getattr in python file triggers Level 3 FULL_REBUILD with reason."""
    dyn_p = tmp_path / "dynamic_model.py"
    dyn_p.write_text("def method(self):\n    func = getattr(self, 'dynamic_name')\n", encoding="utf-8")

    report = analyze_changes([str(dyn_p)], sample_graph)

    assert report.level == StalenessLevel.FULL_REBUILD
    assert report.requires_full_rebuild is True
    assert "dynamic getattr detected" in report.reason


def test_j39_level3_dynamic_safe_eval_rebuild(sample_graph, tmp_path):
    """J39: safe_eval in python file triggers Level 3 FULL_REBUILD with reason."""
    dyn_p = tmp_path / "eval_model.py"
    dyn_p.write_text("from odoo.tools import safe_eval\nval = safe_eval(code)\n", encoding="utf-8")

    report = analyze_changes([str(dyn_p)], sample_graph)

    assert report.level == StalenessLevel.FULL_REBUILD
    assert report.requires_full_rebuild is True
    assert "dynamic safe_eval detected" in report.reason


def test_j40_atomic_graph_swap(tmp_path):
    """J40: verify atomic_write_json and atomic_read_json."""
    graph_file = tmp_path / "active.json"
    data = {"metadata": {"version": 1}, "nodes": [1, 2, 3]}

    atomic_write_json(data, graph_file)
    assert graph_file.exists()

    # Check no leftover tmp files
    tmp_files = list(tmp_path.glob("*.tmp.*"))
    assert len(tmp_files) == 0

    read_data = atomic_read_json(graph_file)
    assert read_data == data


def test_j41_graph_versioning_metadata(sample_graph):
    """J41: verify metadata serialization with git commit hash."""
    serialized = serialize_graph_with_metadata(sample_graph, addons_hash="hash123")
    assert "metadata" in serialized
    meta = serialized["metadata"]

    assert "git_commit" in meta
    assert meta["addons_hash"] == "hash123"
    assert meta["graph_schema_version"] == 3
    assert meta["node_count"] == 3
    assert meta["edge_count"] == 2

    # Deserialization test
    G_deserialized, meta_out = deserialize_graph_with_metadata(serialized)
    assert G_deserialized.number_of_nodes() == 3
    assert G_deserialized.number_of_edges() == 2
    assert meta_out["addons_hash"] == "hash123"


def test_j42_concurrency_20_readers_atomic_swap_stress_test(tmp_path):
    """
    J42 Critical Test: 20 concurrent reader threads reading active.json
    while 1 writer thread continuously performs atomic graph swaps.
    Guarantees 0 JSONDecodeError, 0 partial state reads, 0 exceptions.
    """
    graph_file = tmp_path / "active.json"

    # Initial graph version A (100 nodes)
    g_a = {"metadata": {"version": "A", "node_count": 100}, "nodes": list(range(100)), "links": [{"s": i, "t": i + 1} for i in range(99)]}
    # Version B (300 nodes)
    g_b = {"metadata": {"version": "B", "node_count": 300}, "nodes": list(range(300)), "links": [{"s": i, "t": i + 1} for i in range(299)]}

    atomic_write_json(g_a, graph_file)

    stop_event = threading.Event()
    read_errors = []
    read_counts = [0] * 20
    version_counts = {"A": 0, "B": 0}
    lock = threading.Lock()

    def reader_task(reader_idx: int):
        while not stop_event.is_set():
            try:
                data = atomic_read_json(graph_file)
                ver = data["metadata"]["version"]
                node_cnt = len(data["nodes"])
                link_cnt = len(data["links"])

                # Strict consistency check: never a partial graph
                if ver == "A":
                    assert node_cnt == 100 and link_cnt == 99
                elif ver == "B":
                    assert node_cnt == 300 and link_cnt == 299
                else:
                    pytest.fail(f"Unexpected graph version: {ver}")

                with lock:
                    read_counts[reader_idx] += 1
                    version_counts[ver] += 1

            except Exception as e:
                with lock:
                    read_errors.append((reader_idx, str(e)))

    def writer_task():
        curr_ver = "B"
        while not stop_event.is_set():
            target_data = g_b if curr_ver == "B" else g_a
            atomic_write_json(target_data, graph_file)
            curr_ver = "A" if curr_ver == "B" else "B"
            time.sleep(0.015)  # 15ms swap interval

    # Start 20 readers + 1 writer
    readers = [threading.Thread(target=reader_task, args=(i,)) for i in range(20)]
    writer = threading.Thread(target=writer_task)

    for r in readers:
        r.start()
    writer.start()

    # Run stress test for 1.5 seconds
    time.sleep(1.5)

    stop_event.set()
    writer.join()
    for r in readers:
        r.join()

    # Assertions
    assert len(read_errors) == 0, f"Concurrent read errors detected: {read_errors}"
    total_reads = sum(read_counts)
    assert total_reads > 500, f"Expected >500 total reads across threads, got {total_reads}"
    assert version_counts["A"] > 0, "Expected readers to observe Version A"
    assert version_counts["B"] > 0, "Expected readers to observe Version B"
    print(f"J42 Concurrency Stress Test PASSED: {total_reads} total reads across 20 threads (Version A: {version_counts['A']}, Version B: {version_counts['B']}), 0 errors.")
