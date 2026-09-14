from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH
"""
code_intelligence/tests/test_b1_3.py

Unit tests for Tool button_execution_path(button_label_or_name, model).
Tests:
  1. Synthetic workflow button execution path (UI -> Method -> State transition -> Security)
  2. Real graph test on sale_order module button 'Confirm' / 'action_confirm'
"""

from pathlib import Path
import pytest
import networkx as nx

from code_intelligence.extractor.manifest import parse_manifest

from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.extractor.xml import parse_views_from_xml
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.rules.button_path import button_execution_path


def test_button_execution_path_synthetic():
    """Test button_execution_path on synthetic graph with workflow transition."""
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

    res = button_execution_path(G, "Confirm", "sale.order")
    assert res.model_name == "sale.order"
    assert res.method_name == "action_confirm"
    assert res.origin_states == ["draft"]
    assert res.target_state == "sale"
    assert res.required_groups == ["sales_team.group_sale_salesman"]
    assert len(res.execution_steps) == 4


def test_button_execution_path_real_sale():
    """Test button_execution_path on real sale_order module."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    corpus_root = CORE_ADDONS_PATH
    sale_dir = corpus_root / "sale"

    if sale_dir.exists():
        manifest_p = sale_dir / "__manifest__.py"
        manifest = parse_manifest(manifest_p) if manifest_p.exists() else parse_manifest(CUSTOM_ADDONS_PATH / "miro_ai" / "__manifest__.py")
        mod = ParsedModule(manifest=manifest)
        for py_file in sale_dir.rglob("*.py"):
            mod.models.extend(extract_odoo_models_from_file(py_file))
        for xml_file in sale_dir.rglob("*.xml"):
            mod.views.extend(parse_views_from_xml(xml_file))

        modules = {"sale": mod}
        registry = build_module_symbol_registry(modules)
        builder = OdooGraphBuilder(registry, modules)
        G = builder.build_graph()

        res = button_execution_path(G, "action_confirm", "sale.order")
        assert res.model_name == "sale.order"
        assert res.method_name == "action_confirm"
        assert len(res.execution_steps) >= 3
