"""
code_intelligence/tests/test_j43_j45_symbol_rename_refactoring.py

Unit & Integration tests for  /  :
1. Verifies model rename detection via AST class identity matching.
2. Verifies graph node rewiring (old node ID -> new node ID) preserving attributes and incoming/outgoing edges.
3. Verifies non-rebuild incremental refactoring for model renames (custom.asset.loan -> custom.asset.lending).
"""

import pytest
import networkx as nx
from pathlib import Path

from code_intelligence.extractor.python_extractor import OdooModelDeclaration
from code_intelligence.graph_symbol_refactor import (
    SymbolRename,
    detect_model_renames,
    refactor_rename_in_graph,
)


@pytest.fixture
def asset_loan_graph(tmp_path):
    """Build a graph containing custom.asset.loan with incoming & outgoing edges."""
    file_path = str(tmp_path / "asset_loan.py")
    G = nx.DiGraph()

    # Nodes
    G.add_node(
        "model:custom.asset.loan",
        node_type="Model",
        name="custom.asset.loan",
        class_name="CustomAssetLoan",
        description="Asset Loan Document",
        filepaths=[file_path],
    )
    G.add_node(
        "model:account.move",
        node_type="Model",
        name="account.move",
        class_name="AccountMove",
    )
    G.add_node(
        "rule:rule_asset_loan_user",
        node_type="Rule",
        name="Asset Loan User Rule",
    )

    # Edges
    G.add_edge("model:custom.asset.loan", "model:account.move", edge_type="EXTENDS")
    G.add_edge("rule:rule_asset_loan_user", "model:custom.asset.loan", edge_type="RESTRICTED_BY")

    return G, file_path


def test_j43_detect_model_rename(asset_loan_graph):
    """J43: verify AST detection of model rename (custom.asset.loan -> custom.asset.lending)."""
    G, file_path = asset_loan_graph

    # AST extractions from updated file where _name = "custom.asset.lending"
    new_model_decl = OdooModelDeclaration(
        class_name="CustomAssetLoan",
        filepath=file_path,
        lineno=10,
        name="custom.asset.lending",
    )

    renames = detect_model_renames(G, [new_model_decl], file_path)

    assert len(renames) == 1
    rename = renames[0]
    assert rename.old_symbol == "model:custom.asset.loan"
    assert rename.new_symbol == "model:custom.asset.lending"
    assert rename.old_name == "custom.asset.loan"
    assert rename.new_name == "custom.asset.lending"
    assert rename.class_name == "CustomAssetLoan"


def test_j44_refactor_rename_in_graph_rewires_edges_and_preserves_attrs(asset_loan_graph):
    """J44: verify node replacement, edge rewiring, and attribute preservation."""
    G, file_path = asset_loan_graph

    rename = SymbolRename(
        old_symbol="model:custom.asset.loan",
        new_symbol="model:custom.asset.lending",
        symbol_type="model",
        filepath=file_path,
        class_name="CustomAssetLoan",
        old_name="custom.asset.loan",
        new_name="custom.asset.lending",
    )

    updated_G, summary = refactor_rename_in_graph(G, [rename])

    # Old node removed, new node present
    assert not updated_G.has_node("model:custom.asset.loan")
    assert updated_G.has_node("model:custom.asset.lending")

    # Attributes preserved and updated
    new_attrs = updated_G.nodes["model:custom.asset.lending"]
    assert new_attrs["name"] == "custom.asset.lending"
    assert new_attrs["description"] == "Asset Loan Document"
    assert new_attrs["class_name"] == "CustomAssetLoan"
    assert "custom.asset.loan" in new_attrs["previous_names"]

    # Incoming edge rewired: rule:rule_asset_loan_user -> model:custom.asset.lending
    assert updated_G.has_edge("rule:rule_asset_loan_user", "model:custom.asset.lending")
    assert updated_G.get_edge_data("rule:rule_asset_loan_user", "model:custom.asset.lending")["edge_type"] == "RESTRICTED_BY"

    # Outgoing edge rewired: model:custom.asset.lending -> model:account.move
    assert updated_G.has_edge("model:custom.asset.lending", "model:account.move")
    assert updated_G.get_edge_data("model:custom.asset.lending", "model:account.move")["edge_type"] == "EXTENDS"

    # Summary stats check
    assert summary["renamed_count"] == 1
    assert summary["rewired_edges_count"] == 2


def test_j45_end_to_end_incremental_rename_refactoring(asset_loan_graph):
    """J45: end-to-end refactoring without full rebuild."""
    G, file_path = asset_loan_graph

    new_model_decl = OdooModelDeclaration(
        class_name="CustomAssetLoan",
        filepath=file_path,
        lineno=10,
        name="custom.asset.lending",
    )

    renames = detect_model_renames(G, [new_model_decl], file_path)
    assert len(renames) == 1

    updated_G, summary = refactor_rename_in_graph(G, renames)

    # Verify graph state after refactoring
    assert updated_G.number_of_nodes() == 3
    assert updated_G.number_of_edges() == 2
    assert "model:custom.asset.lending" in updated_G.nodes
