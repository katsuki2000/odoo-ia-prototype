"""
code_intelligence/tests/test_section944_group_names_exposure.py

Unit tests for Section 944 (Point O):
Exposing exact functional/display names of Odoo security groups (res.groups)
in observations produced by who_has_access_to, evaluate_record_rules, and
button_execution_path / xml_view_finder / navigation.
"""

from typing import Optional
import networkx as nx
import pytest

from code_intelligence.rules.access_evaluator import who_has_access_to
from code_intelligence.rules.button_path import button_execution_path
from code_intelligence.rules.group_resolver import (
    get_group_display_name,
    _group_display_name,
)
from code_intelligence.rules.record_rules import evaluate_record_rules
from code_intelligence.rules.xml_view_finder import _find_field_in_xml_views


def _build_security_test_graph() -> nx.DiGraph:
    """Build a test graph with models, ACLs, rules, groups, and buttons."""
    G = nx.DiGraph()

    # Models
    G.add_node("model:purchase.order", node_type="Model", name="purchase.order")
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node("model:maintenance.equipment", node_type="Model", name="maintenance.equipment")

    # Groups
    G.add_node(
        "group:purchase.group_purchase_user",
        node_type="Group",
        xml_id="purchase.group_purchase_user",
        name="User",
        category_id="base.module_category_inventory_purchase",
    )
    G.add_node(
        "group:purchase.group_purchase_manager",
        node_type="Group",
        xml_id="purchase.group_purchase_manager",
        name="Administrator",
        category_id="base.module_category_inventory_purchase",
    )
    G.add_node(
        "group:maintenance.group_equipment_manager",
        node_type="Group",
        xml_id="maintenance.group_equipment_manager",
        name="Equipment Manager",
    )
    G.add_node(
        "group:base.group_user",
        node_type="Group",
        xml_id="base.group_user",
        name="Internal User",
    )

    # Implied hierarchy: manager IMPLIES user
    G.add_edge(
        "group:purchase.group_purchase_manager",
        "group:purchase.group_purchase_user",
        edge_type="IMPLIES",
    )

    # ACL: purchase.order read granted to user (and manager via implied_ids)
    G.add_node(
        "acl:purchase.access_po_user",
        node_type="AccessEntry",
        perm_read=True,
        perm_write=False,
        perm_create=False,
        perm_unlink=False,
        all_authenticated=False,
    )
    G.add_edge("model:purchase.order", "acl:purchase.access_po_user", edge_type="GRANTED_BY")
    G.add_edge("acl:purchase.access_po_user", "group:purchase.group_purchase_user", edge_type="APPLIES_TO_GROUP")

    # Record rule on sale.order
    G.add_node(
        "rule:sale.rule_manager",
        node_type="Rule",
        name="Sales Manager Rule",
        domain_force="[(1, '=', 1)]",
        perm_read=True,
    )
    G.add_edge("model:sale.order", "rule:sale.rule_manager", edge_type="RESTRICTED_BY")
    G.add_edge("rule:sale.rule_manager", "group:purchase.group_purchase_manager", edge_type="APPLIES_TO_GROUP")

    # Button: button_approve on purchase.order restricted to manager
    G.add_node(
        "method:purchase.order.button_approve",
        node_type="Method",
        name="button_approve",
        filepath="addons/purchase/models/purchase_order.py",
        lineno=100,
        end_lineno=130,
    )
    G.add_node("state:purchase.order.to_approve", node_type="State")
    G.add_node("state:purchase.order.purchase", node_type="State")
    G.add_edge(
        "state:purchase.order.to_approve",
        "state:purchase.order.purchase",
        edge_type="TRANSITIONS_VIA",
        method_name="button_approve",
        label_bouton="Approve Order",
        groupe_requis=["purchase.group_purchase_manager"],
    )

    return G


class TestGroupDisplayNameResolution:
    def test_direct_node_display_name(self):
        G = _build_security_test_graph()
        name = get_group_display_name(G, "purchase.group_purchase_manager")
        assert name == "Administrator"

    def test_unprefixed_lookup_resolves_against_graph(self):
        G = _build_security_test_graph()
        name = get_group_display_name(G, "group_purchase_manager")
        assert name == "Administrator"

    def test_prefixed_lookup_resolves_against_unprefixed_node(self):
        G = nx.DiGraph()
        G.add_node("group:group_custom_role", node_type="Group", name="Custom Role")
        name = get_group_display_name(G, "my_module.group_custom_role")
        assert name == "Custom Role"

    def test_xml_fallback_resolves_sales_team_groups(self):
        """sales_team groups defined in core addons XML should resolve even with an empty graph."""
        G = nx.DiGraph()
        name_mgr = get_group_display_name(G, "sales_team.group_sale_manager")
        assert name_mgr == "Administrator"

        name_user = get_group_display_name(G, "sales_team.group_sale_salesman")
        assert name_user == "User: Own Documents Only"

    def test_unknown_group_returns_empty_string(self):
        G = nx.DiGraph()
        assert get_group_display_name(G, "non_existent_module.non_existent_group") == ""

    def test_compat_alias_group_display_name(self):
        G = _build_security_test_graph()
        assert _group_display_name(G, "purchase.group_purchase_manager") == "Administrator"


class TestWhoHasAccessToGroupExposure:
    def test_matrix_all_exposes_group_names_and_implied_ids(self):
        G = _build_security_test_graph()
        res = who_has_access_to(G, "purchase.order", permission="all")
        # Direct ACL group has name ('User')
        assert "purchase.group_purchase_user ('User')" in res.summary_text
        # Inheriting group has name ('Administrator') and source has name ('User')
        assert "purchase.group_purchase_manager ('Administrator')" in res.summary_text
        assert "via implied_ids <- purchase.group_purchase_user ('User')" in res.summary_text

    def test_single_permission_all_groups_exposes_display_names(self):
        G = _build_security_test_graph()
        res = who_has_access_to(G, "purchase.order", permission="read")
        assert "purchase.group_purchase_user ('User')" in res.summary_text
        assert "purchase.group_purchase_manager ('Administrator')" in res.summary_text
        assert "(via implied_ids <- purchase.group_purchase_user ('User'))" in res.summary_text

    def test_single_permission_specific_group_exposes_display_name(self):
        G = _build_security_test_graph()
        res = who_has_access_to(
            G, "purchase.order", permission="read", group_id="purchase.group_purchase_manager"
        )
        assert "purchase.group_purchase_manager" in res.summary_text
        assert "('Administrator')" in res.summary_text
        assert "via implied_ids <- purchase.group_purchase_user ('User')" in res.summary_text


class TestEvaluateRecordRulesGroupExposure:
    def test_applicable_group_rule_displays_group_names(self):
        G = _build_security_test_graph()
        user_groups = ["purchase.group_purchase_manager"]
        res = evaluate_record_rules(G, "sale.order", permission="read", user_groups=user_groups)
        assert "Sales Manager Rule" in res.summary_text
        assert "groupes: purchase.group_purchase_manager ('Administrator')" in res.summary_text

    def test_ignored_group_rule_displays_group_names(self):
        G = _build_security_test_graph()
        user_groups = ["base.group_user"]
        res = evaluate_record_rules(G, "sale.order", permission="read", user_groups=user_groups)
        assert "Règles de Groupe ignorées" in res.summary_text
        assert "purchase.group_purchase_manager ('Administrator')" in res.summary_text

    def test_conclusion_formats_evaluated_groups_with_display_names(self):
        G = _build_security_test_graph()
        user_groups = ["base.group_user"]
        res = evaluate_record_rules(G, "sale.order", permission="read", user_groups=user_groups)
        assert "base.group_user ('Internal User')" in res.summary_text


class TestButtonExecutionPathGroupExposure:
    def test_button_required_groups_displays_display_names(self):
        G = _build_security_test_graph()
        res = button_execution_path(G, "Approve Order", "purchase.order")
        assert "purchase.group_purchase_manager ('Administrator')" in res.summary_text
        assert any(
            "purchase.group_purchase_manager ('Administrator')" in step
            for step in res.execution_steps
        )
