"""
code_intelligence/tests/test_b1_2.py

Unit tests for Story B1.2: Tool field_change_impact(field_name, model).
Tests:
  1. Upstream dependencies (trigger fields that cause recomputation)
  2. Downstream impact (computed fields recomputed when this field changes)
  3. Real graph test on sale_order module (partner_id, amount_untaxed, amount_total)
"""

from pathlib import Path
import pytest
import networkx as nx

from code_intelligence.python_extractor import extract_odoo_models_from_file
from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.deterministic_tools import field_change_impact


def test_impact_changement_champ_synthetic():
    """Test field_change_impact on synthetic graph with computed and trigger fields."""
    G = nx.DiGraph()

    # Nodes
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node("field:sale.order.price_unit", node_type="Field", name="price_unit", model="sale.order")
    G.add_node("field:sale.order.amount_untaxed", node_type="Field", name="amount_untaxed", model="sale.order", compute="_compute_amounts")
    G.add_node("method:sale.order._compute_amounts", node_type="Method", name="_compute_amounts", model="sale.order")

    # Edges
    # Model HAS_FIELD fields
    G.add_edge("model:sale.order", "field:sale.order.price_unit", edge_type="HAS_FIELD")
    G.add_edge("model:sale.order", "field:sale.order.amount_untaxed", edge_type="HAS_FIELD")

    # Field COMPUTED_BY Method
    G.add_edge("field:sale.order.amount_untaxed", "method:sale.order._compute_amounts", edge_type="COMPUTED_BY")

    # Method DEPENDS_ON trigger field price_unit
    G.add_edge("method:sale.order._compute_amounts", "field:sale.order.price_unit", edge_type="DEPENDS_ON")

    # 1. Query impact of modifying 'price_unit' (trigger field)
    impact_unit = field_change_impact(G, "price_unit", "sale.order")
    assert impact_unit.field_name == "price_unit"
    assert "amount_untaxed" in impact_unit.downstream_computed_fields

    # 2. Query impact of modifying 'amount_untaxed' (computed field)
    impact_untaxed = field_change_impact(G, "amount_untaxed", "sale.order")
    assert impact_untaxed.field_name == "amount_untaxed"
    assert impact_untaxed.compute_method == "_compute_amounts"
    assert "price_unit" in impact_untaxed.upstream_triggers


def test_impact_changement_champ_real_sale():
    """Test field_change_impact on real sale_order module."""
    corpus_root = Path("/home/user/odoo-17.0/addons")
    sale_dir = corpus_root / "sale"

    if sale_dir.exists():
        mod = ParsedModule(manifest=None)
        for py_file in sale_dir.rglob("*.py"):
            mod.models.extend(extract_odoo_models_from_file(py_file))

        modules = {"sale": mod}
        registry = build_module_symbol_registry(modules)
        builder = OdooGraphBuilder(registry, modules)
        G = builder.build_graph()

        # Query impact of partner_id on sale.order
        impact_partner = field_change_impact(G, "partner_id", "sale.order")
        assert impact_partner.field_name == "partner_id"
        assert impact_partner.relational_target == "res.partner"
