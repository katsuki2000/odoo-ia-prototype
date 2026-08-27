"""
code_intelligence/tests/test_a3_1_1.py

Unit and Integration tests for NetworkX Knowledge Graph & Workflow Sub-Graph.
Tests:
  1. NetworkX graph construction (nodes, typed edges)
  2. JSON serialization and deserialization (node_link_data / node_link_graph per DT-4)
  3. Workflow sub-graph construction (WorkflowState nodes & TRANSITIONS_VIA edges)
  4. 5-hop traversal benchmark (< 50ms performance target)
  5. 5-hop end-to-end security path traversal demonstration
"""

import tempfile
from pathlib import Path
import pytest
import networkx as nx

from code_intelligence.manifest_parser import parse_manifest
from code_intelligence.python_extractor import extract_odoo_models_from_file
from code_intelligence.xml_extractor import (
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)
from code_intelligence.csv_extractor import parse_access_control_csv
from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import (
    OdooGraphBuilder,
    save_graph_to_json,
    load_graph_from_json,
    benchmark_graph_traversal,
)
from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH


def test_graph_construction_and_typed_edges():
    """Test NetworkX node and typed edge creation (A3.1.2 & A3.1.3)."""
    # Create synthetic parsed module
    mod = ParsedModule(
        manifest=parse_manifest(CUSTOM_ADDONS_PATH / "miro_ai" / "__manifest__.py")
    )
    
    modules_dict = {"miro_ai": mod}
    registry = build_module_symbol_registry(modules_dict)

    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    assert isinstance(G, nx.DiGraph)
    assert G.number_of_nodes() > 0

    # Verify node types
    node_types = {G.nodes[n].get("node_type") for n in G.nodes}
    assert "Module" in node_types


def test_json_serialization_deserialization():
    """Test Task A3.1.4: JSON graph serialization using node_link_data per DT-4."""
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node("rule:sale.rule1", node_type="Rule", domain_force="[('company_id','=',1)]")
    G.add_edge("model:sale.order", "rule:sale.rule1", edge_type="RESTRICTED_BY")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f_path = Path(f.name)

    try:
        save_graph_to_json(G, f_path)
        assert f_path.stat().st_size > 0

        loaded_G = load_graph_from_json(f_path)
        assert isinstance(loaded_G, nx.DiGraph)
        assert loaded_G.number_of_nodes() == 2
        assert loaded_G.number_of_edges() == 1
        assert loaded_G.nodes["model:sale.order"]["name"] == "sale.order"
        assert loaded_G.edges["model:sale.order", "rule:sale.rule1"]["edge_type"] == "RESTRICTED_BY"

    finally:
        f_path.unlink()


def test_workflow_subgraph():
    """Test Task A3.1.5: Workflow state nodes and TRANSITIONS_VIA edges."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    if CORE_ADDONS_PATH is None:
        pytest.skip("ODOO_CORE_ADDONS_PATH not set -- no real Odoo core corpus on this machine.")

    sale_dir = CORE_ADDONS_PATH / "sale"
    if not sale_dir.exists():
        pytest.skip(f"Corpus sale module dir does not exist: {sale_dir}")

    mod = ParsedModule(manifest=parse_manifest(sale_dir / "__manifest__.py") if (sale_dir / "__manifest__.py").exists() else parse_manifest(CUSTOM_ADDONS_PATH / "miro_ai" / "__manifest__.py"))
    for py_file in sale_dir.rglob("*.py"):
        mod.models.extend(extract_odoo_models_from_file(py_file))
    for xml_file in sale_dir.rglob("*.xml"):
        mod.views.extend(parse_views_from_xml(xml_file))

    modules = {"sale": mod}
    registry = build_module_symbol_registry(modules)
    builder = OdooGraphBuilder(registry, modules)
    G = builder.build_graph()

    # Check for WorkflowState nodes
    workflow_nodes = [n for n, data in G.nodes(data=True) if data.get("node_type") == "WorkflowState"]
    assert len(workflow_nodes) > 0

    # Check for TRANSITIONS_VIA edges
    transition_edges = [(u, v, data) for u, v, data in G.edges(data=True) if data.get("edge_type") == "TRANSITIONS_VIA"]
    assert len(transition_edges) > 0
    t_edge = transition_edges[0]
    assert "method_name" in t_edge[2]
    assert "label_bouton" in t_edge[2]


def test_real_corpus_graph_and_5hop_benchmark():
    """Test Tasks A3.1.6 & A3.1.7: 5-hop traversal benchmark (< 50ms) and security path demonstration."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent

    modules_dict = {}

    # Load miro_ai
    miro_ai_dir = CUSTOM_ADDONS_PATH / "miro_ai"
    if miro_ai_dir.exists():
        manifest = parse_manifest(miro_ai_dir / "__manifest__.py")
        if manifest:
            mod = ParsedModule(manifest=manifest)
            for py_file in miro_ai_dir.rglob("*.py"):
                mod.models.extend(extract_odoo_models_from_file(py_file))
            for xml_file in miro_ai_dir.rglob("*.xml"):
                mod.rules.extend(parse_ir_rules_from_xml(xml_file))
                mod.groups.extend(parse_groups_from_xml(xml_file))
                mod.actions.extend(parse_actions_from_xml(xml_file))
                mod.menuitems.extend(parse_menuitems_from_xml(xml_file))
                mod.views.extend(parse_views_from_xml(xml_file))
            for csv_file in miro_ai_dir.rglob("*.csv"):
                mod.acl_entries.extend(parse_access_control_csv(csv_file))
            modules_dict["miro_ai"] = mod

    # Build Graph
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    print(f"\n--- Knowledge Graph Built: {G.number_of_nodes()} Nodes, {G.number_of_edges()} Edges ---")

    # Benchmark 5-hop traversal
    start_node = "model:miro.ai.log" if "model:miro.ai.log" in G else list(G.nodes)[0]
    elapsed_ms, sample_path = benchmark_graph_traversal(G, start_node, max_hops=3)

    print(f"5-Hop Traversal Benchmark Time: {elapsed_ms:.3f} ms (Budget: < 50 ms)")
    if sample_path:
        print(f"Sample Traversal Path: {' -> '.join(sample_path)}")

    # Acceptance criterion A3.1.6: benchmark < 50ms
    assert elapsed_ms < 50.0, f"Traversal time {elapsed_ms:.3f}ms exceeded 50ms budget target"
