"""
code_intelligence/tests/test_bloc10_j37_39_staleness_detection.py

Unit tests for , J37-J39 — Staleness Detection & Incremental Graph Update.

Covers the 3 staleness levels:
  Level 1 (FILE)   : detect that a source file changed (hash mismatch).
  Level 2 (EDGE)   : after a module changes, identify cross-module edges that
                     reference nodes from that module and are now potentially stale.
  Level 3 (COVERED): cases not resolvable by local reparse are flagged explicitly
                     (e.g. cross-module rename — handled by , not here).

Critère de fin J37-J39 (from real_plan.md):
  "Implémenter les trois niveaux de mise à jour (recalcul du fichier modifié +
   propagation aux arêtes invalidées ailleurs dans le graphe + détection des cas
   non couverts par un recalcul local)."
"""

import json

import networkx as nx

from code_intelligence.graph.staleness import (
    StalenessLevel,
    analyze_changes,
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
# Level 1: File change detection
# ──────────────────────────────────────────────────────────────────────────────

def test_analyze_changes_reports_nothing_when_no_file_changed(tmp_path):
    """Level 1: nothing is stale when no file changed."""
    report = analyze_changes([], nx.DiGraph(), module_roots={"sale": tmp_path})

    assert not report.is_stale
    assert report.level == StalenessLevel.CLEAN
    assert len(report.changed_modules) == 0


def test_analyze_changes_attributes_changed_file_to_its_module(tmp_path):
    """Level 1: a changed source file marks its module as changed."""
    f = tmp_path / "model.py"
    f.write_text("original content", encoding="utf-8")

    report = analyze_changes([str(f)], nx.DiGraph(), module_roots={"sale": tmp_path})

    assert report.is_stale
    assert "sale" in report.changed_modules


def test_analyze_changes_treats_unindexed_new_file_as_stale(tmp_path):
    """Level 1: a new file that no graph node knows about forces a full rebuild."""
    f = tmp_path / "new_model.py"
    f.write_text("class NewModel: pass", encoding="utf-8")

    report = analyze_changes([str(f)], nx.DiGraph(), module_roots={"sale": tmp_path})

    assert report.is_stale
    assert report.level == StalenessLevel.FULL_REBUILD
    assert "sale" in report.changed_modules


def test_analyze_changes_treats_deleted_file_as_stale(tmp_path):
    """Level 1: a path that no longer exists on disk is a change, attributed to its module."""
    deleted_path = str(tmp_path / "deleted.py")

    report = analyze_changes([deleted_path], nx.DiGraph(), module_roots={"sale": tmp_path})

    assert report.is_stale
    assert "sale" in report.changed_modules


# ──────────────────────────────────────────────────────────────────────────────
# Level 2: Cross-module edge invalidation propagation
# ──────────────────────────────────────────────────────────────────────────────

def test_analyze_changes_propagates_invalidation_to_dependent_modules(tmp_path):
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

    report = analyze_changes(
        [str(f)],
        G,
        module_roots={"sale": sale_root, "stock": tmp_path / "stock"},
    )

    assert report.is_stale
    assert "sale" in report.changed_modules
    assert len(report.affected_cross_edges) >= 1 or len(report.propagated_nodes) >= 1


def test_analyze_changes_does_not_flag_edges_within_unchanged_modules(tmp_path):
    """
    Level 2: DEFINED_IN edges inside a stable module are NOT flagged as stale.
    """
    G = _make_graph_with_cross_module_edge()
    sale_root = tmp_path / "sale"
    sale_root.mkdir()
    stock_root = tmp_path / "stock"
    stock_root.mkdir()

    report = analyze_changes([], G, module_roots={"sale": sale_root, "stock": stock_root})

    assert not report.is_stale
    assert report.affected_cross_edges == []


# ──────────────────────────────────────────────────────────────────────────────
# Level 3: Uncoverable cases are flagged explicitly
# ──────────────────────────────────────────────────────────────────────────────

def test_analyze_changes_flags_potential_rename_as_uncoverable(tmp_path):
    """
    Level 3: when a changed file matches no node of the graph (here the old
    path of a renamed file), the change is flagged as a potential rename
    (uncoverable without PyRef).
    """
    G = _make_graph_with_cross_module_edge()
    sale_root = tmp_path / "sale"
    sale_root.mkdir()
    old_file = sale_root / "sale_order.py"
    new_file = sale_root / "sale_document.py"
    new_file.write_text("class SaleDocument: pass", encoding="utf-8")

    report = analyze_changes(
        [str(old_file), str(new_file)],
        G,
        module_roots={"sale": sale_root, "stock": tmp_path / "stock"},
    )

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

    report = analyze_changes([str(f)], G, module_roots={"sale": sale_root})

    serialised = json.dumps(report.to_dict())
    data = json.loads(serialised)
    assert "is_stale" in data
    assert "changed_modules" in data
    assert "affected_cross_edges" in data
