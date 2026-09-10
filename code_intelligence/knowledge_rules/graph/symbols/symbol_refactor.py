"""
code_intelligence/graph_symbol_refactor.py

Incremental Symbol & Model Rename Handler:
Detects and processes symbol/model renames across the Odoo Code Intelligence knowledge graph.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
import logging
import networkx as nx

from code_intelligence.knowledge_rules.extractor.python_extractor import OdooModelDeclaration

_logger = logging.getLogger(__name__)


@dataclass
class SymbolRename:
    """Represents a detected symbol or model rename."""
    old_symbol: str        # e.g. "model:custom.asset.loan"
    new_symbol: str        # e.g. "model:custom.asset.lending"
    symbol_type: str       # "model", "field", "group", "xml_id"
    filepath: str
    class_name: Optional[str] = None
    old_name: str = ""     # e.g. "custom.asset.loan"
    new_name: str = ""     # e.g. "custom.asset.lending"


def detect_model_renames(
    G: nx.DiGraph,
    new_models: List[OdooModelDeclaration],
    filepath: str,
) -> List[SymbolRename]:
    """
    Compare existing models in graph G associated with filepath
    against newly extracted AST model declarations to identify renamed models.
    Identifies renames when Python class_name matches but _name changed.
    """
    clean_fp = str(Path(filepath).resolve())
    renames: List[SymbolRename] = []

    # Find existing model nodes in G for this filepath
    existing_model_nodes: Dict[str, Dict[str, Any]] = {}
    for node, attrs in G.nodes(data=True):
        if attrs.get("node_type") == "Model":
            fps = attrs.get("filepaths") or attrs.get("source_files") or []
            node_fp = attrs.get("filepath")
            if node_fp and str(Path(node_fp).resolve()) == clean_fp:
                existing_model_nodes[node] = attrs
            elif any(str(Path(f).resolve()) == clean_fp for f in fps):
                existing_model_nodes[node] = attrs

    if not existing_model_nodes:
        return renames

    # Map existing class_name -> node_id
    class_to_old_node: Dict[str, str] = {}
    for node_id, attrs in existing_model_nodes.items():
        c_name = attrs.get("class_name")
        if c_name:
            class_to_old_node[c_name] = node_id

    # Check new AST model declarations
    for m in new_models:
        if m.name and m.class_name in class_to_old_node:
            old_node_id = class_to_old_node[m.class_name]
            old_model_name = G.nodes[old_node_id].get("name") or old_node_id.replace("model:", "")
            new_model_name = m.name

            if old_model_name != new_model_name:
                new_node_id = f"model:{new_model_name}"
                renames.append(
                    SymbolRename(
                        old_symbol=old_node_id,
                        new_symbol=new_node_id,
                        symbol_type="model",
                        filepath=filepath,
                        class_name=m.class_name,
                        old_name=old_model_name,
                        new_name=new_model_name,
                    )
                )

    return renames


def refactor_rename_in_graph(
    G: nx.DiGraph,
    renames: List[SymbolRename],
) -> Tuple[nx.DiGraph, Dict[str, Any]]:
    """
    J43-J45: Perform graph refactoring for a list of detected symbol renames.
    Replaces node IDs in NetworkX graph, rewires all edges, preserves attributes,
    and returns (updated_G, summary_report).
    """
    if not renames:
        return G, {"renamed_count": 0, "rewired_edges_count": 0, "details": []}

    H = G.copy()
    rewired_edges_count = 0
    details = []

    for r in renames:
        old_id = r.old_symbol
        new_id = r.new_symbol

        if not H.has_node(old_id):
            _logger.warning("Rename target node %s not found in graph", old_id)
            continue

        # Preserve node attributes and update name
        attrs = dict(H.nodes[old_id])
        attrs["name"] = r.new_name or attrs.get("name")
        attrs["previous_names"] = attrs.get("previous_names", []) + [r.old_name]

        # Add new node
        H.add_node(new_id, **attrs)

        # Rewire incoming edges (predecessors -> new_id)
        for pred in list(H.predecessors(old_id)):
            edge_attrs = dict(H.get_edge_data(pred, old_id))
            H.add_edge(pred, new_id, **edge_attrs)
            rewired_edges_count += 1

        # Rewire outgoing edges (new_id -> successors)
        for succ in list(H.successors(old_id)):
            edge_attrs = dict(H.get_edge_data(old_id, succ))
            H.add_edge(new_id, succ, **edge_attrs)
            rewired_edges_count += 1

        # Remove old node
        H.remove_node(old_id)

        details.append({
            "old_symbol": old_id,
            "new_symbol": new_id,
            "class_name": r.class_name,
            "filepath": r.filepath,
        })
        _logger.info("Refactored graph node %s -> %s (class=%s)", old_id, new_id, r.class_name)

    summary = {
        "renamed_count": len(details),
        "rewired_edges_count": rewired_edges_count,
        "details": details,
    }
    return H, summary
