"""
code_intelligence/tests/test_b1_3.py

Unit tests for Story B1.3: Tool chemin_execution_bouton(button_label_or_name, model).
Tests:
  1. Synthetic workflow button execution path (UI -> Method -> State transition -> Security)
  2. Real graph test on sale_order module button 'Confirm' / 'action_confirm'
"""

from pathlib import Path
import pytest
import networkx as nx

from code_intelligence.manifest_parser import parse_manifest

from code_intelligence.python_extractor import extract_odoo_models_from_file
from code_intelligence.xml_extractor import parse_views_from_xml
from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.deterministic_tools import chemin_execution_bouton


def test_chemin_execution_bouton_synthetic():
    """Test chemin_execution_bouton on synthetic graph with workflow transition."""
    G = nx.DiGraph()

    # Nodes
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node("method:sale.order.action_confirm", node_type="Method", name="action_confirm", model="sale.order")
    G.add_node("state:sale.order.draft", node_type="WorkflowState", model="sale.order", state_value="draft")
    G.add_node("state:sale.order.sale", node_type="WorkflowState", model="sale.order", state_value="sale")

    # Edges
    G.add_edge(
        "state:sale.order.draft",
        "state:sale.order.sale",
        edge_type="TRANSITIONS_VIA",
        method_name="action_confirm",
        label_bouton="Confirm",
        groupe_requis=["sales_team.group_sale_salesman"]
    )

    res = chemin_execution_bouton(G, "Confirm", "sale.order")
    assert res.model_name == "sale.order"
    assert res.method_name == "action_confirm"
    assert res.origin_states == ["draft"]
    assert res.target_state == "sale"
    assert res.required_groups == ["sales_team.group_sale_salesman"]
    assert len(res.execution_steps) == 4


def test_chemin_execution_bouton_real_sale():
    """Test chemin_execution_bouton on real sale_order module."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    corpus_root = Path(__file__).resolve().parent.parent.parent / "fake_data" / "code"
    sale_dir = corpus_root / "sale"

    if sale_dir.exists():
        manifest_p = sale_dir / "__manifest__.py"
        manifest = parse_manifest(manifest_p) if manifest_p.exists() else parse_manifest(root_dir / "odoo17-dev" / "addons" / "miro_ai" / "__manifest__.py")
        mod = ParsedModule(manifest=manifest)
        for py_file in sale_dir.rglob("*.py"):
            mod.models.extend(extract_odoo_models_from_file(py_file))
        for xml_file in sale_dir.rglob("*.xml"):
            mod.views.extend(parse_views_from_xml(xml_file))

        modules = {"sale": mod}
        registry = build_module_symbol_registry(modules)
        builder = OdooGraphBuilder(registry, modules)
        G = builder.build_graph()

        res = chemin_execution_bouton(G, "action_confirm", "sale.order")
        assert res.model_name == "sale.order"
        assert res.method_name == "action_confirm"
        assert len(res.execution_steps) >= 3
