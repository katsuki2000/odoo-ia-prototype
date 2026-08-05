"""
code_intelligence/tests/test_bloc10_j37_39_staleness_detection.py

Unit tests for Bloc 10, J37-J39 — Staleness Detection & Incremental Graph Update.

Covers the 3 staleness levels:
  Level 1 (FILE)   : detect that a source file changed (hash mismatch).
  Level 2 (EDGE)   : after a module changes, identify cross-module edges that
                     reference nodes from that module and are now potentially stale.
  Level 3 (COVERED): cases not resolvable by local reparse are flagged explicitly
                     (e.g. cross-module rename — handled by Bloc 11, not here).

Critère de fin J37-J39 (from real_plan.md):
  "Implémenter les trois niveaux de mise à jour (recalcul du fichier modifié +
   propagation aux arêtes invalidées ailleurs dans le graphe + détection des cas
   non couverts par un recalcul local)."
"""

import hashlib
import json
from pathlib import Path

import networkx as nx
import pytest

from code_intelligence.graph_staleness_detector import (
    StalenessLevel,
    STALENESS_LEVEL_FILE,
    STALENESS_LEVEL_EDGE,
    STALENESS_LEVEL_UNCOVERABLE,
    GraphStalenessDetector,
    StalenessReport,
    build_file_hash_index,
    compute_file_hash,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_graph_with_cross_module_edge() -> nx.DiGraph:
    """
    Minimal graph:
      module:sale  → DEFINED_IN → model:sale.order          (from sale)
      module:stock → DEFINED_IN → model:stock.picking        (from stock)
      model:stock.picking → RELATES_TO → model:sale.order   (cross-module edge)
    """
    G = nx.DiGraph()
    G.add_node("module:sale",  node_type="Module", name="sale")
    G.add_node("module:stock", node_type="Module", name="stock")
    G.add_node(
        "model:sale.order",
        node_type="Model",
        name="sale.order",
        source_module="sale",
        source_files=["addons/sale/models/sale_order.py"],
    )
    G.add_node(
        "model:stock.picking",
        node_type="Model",
        name="stock.picking",
        source_module="stock",
        source_files=["addons/stock/models/stock_picking.py"],
    )
    G.add_edge("model:sale.order",    "module:sale",  edge_type="DEFINED_IN")
    G.add_edge("model:stock.picking", "module:stock", edge_type="DEFINED_IN")
    # Cross-module edge: stock references sale
    G.add_edge(
        "model:stock.picking",
        "model:sale.order",
        edge_type="RELATES_TO",
        source_module="stock",
    )
    return G


# ──────────────────────────────────────────────────────────────────────────────
# J37-J39 — Level 1: File hash staleness detection
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_file_hash_is_deterministic(tmp_path):
    """Level 1: same content → same hash, always."""
    f = tmp_path / "model.py"
    f.write_text("class SaleOrder(models.Model): _name = 'sale.order'", encoding="utf-8")
    h1 = compute_file_hash(f)
    h2 = compute_file_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


def test_compute_file_hash_changes_on_content_change(tmp_path):
    """Level 1: different content → different hash."""
    f = tmp_path / "model.py"
    f.write_text("original", encoding="utf-8")
    h_before = compute_file_hash(f)
    f.write_text("modified", encoding="utf-8")
    h_after = compute_file_hash(f)
    assert h_before != h_after


def test_build_file_hash_index_covers_all_files(tmp_path):
    """Level 1: hash index covers every .py and .xml file in the module root."""
    (tmp_path / "models").mkdir()
    (tmp_path / "security").mkdir()
    (tmp_path / "models" / "sale_order.py").write_text("class X: pass", encoding="utf-8")
    (tmp_path / "security" / "ir.model.access.csv").write_text("id,model_id", encoding="utf-8")
    (tmp_path / "security" / "rules.xml").write_text("<odoo/>", encoding="utf-8")
    (tmp_path / "__manifest__.py").write_text("{'name': 'Sale'}", encoding="utf-8")

    index = build_file_hash_index(tmp_path)
    paths = {Path(p) for p in index}
    assert any(p.name == "sale_order.py" for p in paths)
    assert any(p.name == "rules.xml" for p in paths)
    assert any(p.name == "__manifest__.py" for p in paths)


def test_detector_reports_no_staleness_when_unchanged(tmp_path):
    """Level 1: detector reports nothing stale when files are identical."""
    f = tmp_path / "model.py"
    f.write_text("unchanged", encoding="utf-8")
    old_index = {str(f): compute_file_hash(f)}

    detector = GraphStalenessDetector(graph=nx.DiGraph(), module_roots={"sale": tmp_path})
    report = detector.detect(old_hash_index=old_index)

    assert not report.is_stale
    assert report.level == StalenessLevel.CLEAN
    assert len(report.changed_modules) == 0
    assert not report.is_stale


def test_detector_detects_changed_file(tmp_path):
    """Level 1: detector detects when a source file's hash has changed."""
    f = tmp_path / "model.py"
    f.write_text("original content", encoding="utf-8")
    old_index = {str(f): "aaaa1111" * 8}  # deliberately wrong / stale hash

    detector = GraphStalenessDetector(graph=nx.DiGraph(), module_roots={"sale": tmp_path})
    report = detector.detect(old_hash_index=old_index)

    assert report.is_stale
    assert "sale" in report.changed_modules


def test_detector_detects_new_file_as_stale(tmp_path):
    """Level 1: a file absent from the old index is treated as a change."""
    f = tmp_path / "new_model.py"
    f.write_text("class NewModel: pass", encoding="utf-8")
    old_index: dict = {}  # empty → new file not in old index

    detector = GraphStalenessDetector(graph=nx.DiGraph(), module_roots={"sale": tmp_path})
    report = detector.detect(old_hash_index=old_index)

    assert report.is_stale
    assert "sale" in report.changed_modules


def test_detector_detects_deleted_file_as_stale(tmp_path):
    """Level 1: a file in the old index that no longer exists → stale."""
    deleted_path = str(tmp_path / "deleted.py")
    old_index = {deleted_path: "deadbeef" * 8}

    detector = GraphStalenessDetector(graph=nx.DiGraph(), module_roots={"sale": tmp_path})
    report = detector.detect(old_hash_index=old_index)

    assert report.is_stale
    assert "sale" in report.changed_modules


# ──────────────────────────────────────────────────────────────────────────────
# J37-J39 — Level 2: Cross-module edge invalidation propagation
# ──────────────────────────────────────────────────────────────────────────────

def test_detector_propagates_invalidation_to_dependent_modules(tmp_path):
    """
    Level 2: when 'sale' changes, cross-module edges in 'stock' that reference
    sale.order nodes are identified as potentially stale.
    """
    G = _make_graph_with_cross_module_edge()
    sale_root = tmp_path / "sale"
    sale_root.mkdir()
    f = sale_root / "sale_order.py"
    f.write_text("class SaleOrder: pass", encoding="utf-8")
    G.nodes["model:sale.order"]["source_files"] = [str(f)]

    old_index = {str(f): "stale_hash" * 8}

    detector = GraphStalenessDetector(
        graph=G,
        module_roots={"sale": sale_root, "stock": tmp_path / "stock"},
    )
    report = detector.detect(old_hash_index=old_index)

    assert report.is_stale
    assert "sale" in report.changed_modules
    assert len(report.affected_cross_edges) >= 1 or len(report.propagated_nodes) >= 1


def test_detector_does_not_flag_edges_within_unchanged_modules(tmp_path):
    """
    Level 2: DEFINED_IN edges inside a stable module are NOT flagged as stale.
    """
    G = _make_graph_with_cross_module_edge()
    # Both module roots exist but no files changed (empty old_index = all hashes match current)
    sale_root = tmp_path / "sale"
    sale_root.mkdir()
    stock_root = tmp_path / "stock"
    stock_root.mkdir()

    detector = GraphStalenessDetector(
        graph=G,
        module_roots={"sale": sale_root, "stock": stock_root},
    )
    # No old index → nothing to compare → trivially not stale
    report = detector.detect(old_hash_index={})

    # With empty directories, no files found → no changes
    assert not report.is_stale
    assert report.affected_cross_edges == []


# ──────────────────────────────────────────────────────────────────────────────
# J37-J39 — Level 3: Uncoverable cases are flagged explicitly
# ──────────────────────────────────────────────────────────────────────────────

def test_detector_flags_potential_rename_as_uncoverable(tmp_path):
    """
    Level 3: when a node disappears from the rebuilt partial graph but its
    source file still exists, the detector flags it as a potential rename
    (uncoverable without PyRef — Bloc 11).
    """
    G = _make_graph_with_cross_module_edge()
    # sale root with a file that was renamed in Python (sale_order → sale_document)
    sale_root = tmp_path / "sale"
    sale_root.mkdir()
    # Old index had sale_order.py; now only sale_document.py exists
    old_file = sale_root / "sale_order.py"
    new_file = sale_root / "sale_document.py"
    new_file.write_text("class SaleDocument: pass", encoding="utf-8")
    old_index = {str(old_file): "old_hash" * 8}

    detector = GraphStalenessDetector(
        graph=G,
        module_roots={"sale": sale_root, "stock": tmp_path / "stock"},
    )
    report = detector.detect(old_hash_index=old_index)

    assert report.is_stale
    assert report.has_uncoverable_cases
    assert any("rename" in reason.lower() for reason in report.uncoverable_reasons)


def test_staleness_report_serialisable(tmp_path):
    """StalenessReport must be JSON-serialisable (needed for API response + log)."""
    G = _make_graph_with_cross_module_edge()
    sale_root = tmp_path / "sale"
    sale_root.mkdir()
    f = sale_root / "model.py"
    f.write_text("class X: pass", encoding="utf-8")
    old_index = {str(f): "stale" * 8}

    detector = GraphStalenessDetector(
        graph=G,
        module_roots={"sale": sale_root},
    )
    report = detector.detect(old_hash_index=old_index)
    # Must not raise
    serialised = json.dumps(report.to_dict())
    data = json.loads(serialised)
    assert "is_stale" in data
    assert "changed_modules" in data
    assert "affected_cross_edges" in data
