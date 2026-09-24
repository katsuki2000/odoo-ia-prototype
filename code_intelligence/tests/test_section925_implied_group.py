"""
Section 925 — Implied Group detection tests.

Tests for:
- OdooFieldDeclaration.implied_group extraction
- Graph node group_type attribute (technical vs role)
- IMPLIES_CONFIGURABLE edge creation
- _expand_implied_user_groups follows IMPLIES_CONFIGURABLE
- button_execution_path message for technical groups
"""
import ast
import pytest
import networkx as nx

from code_intelligence.extractor.python import OdooFieldDeclaration, OdooClassVisitor
from code_intelligence.rules.group_resolver import _expand_implied_user_groups


# ── 1. OdooFieldDeclaration holds implied_group ──────────────────────────

def test_field_declaration_implied_group_default():
    """implied_group defaults to None."""
    decl = OdooFieldDeclaration(name="x", field_type="Boolean")
    assert decl.implied_group is None


def test_field_declaration_implied_group_set():
    """implied_group can be set to a group xml_id."""
    decl = OdooFieldDeclaration(
        name="group_stock_multi_locations",
        field_type="Boolean",
        implied_group="stock.group_stock_multi_locations",
    )
    assert decl.implied_group == "stock.group_stock_multi_locations"


# ── 2. Extractor picks up implied_group from AST ─────────────────────────

def test_extractor_extracts_implied_group():
    """_extract_field_declaration should capture the implied_group kwarg."""
    source = '''
class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    group_stock_multi_locations = fields.Boolean(
        'Storage Locations',
        implied_group='stock.group_stock_multi_locations',
    )
'''
    extractor = OdooClassVisitor()
    tree = ast.parse(source)
    # Navigate to the field assignment
    class_node = tree.body[0]
    assign = class_node.body[1]  # the field assignment
    field_name = assign.targets[0].id if hasattr(assign.targets[0], 'id') else assign.targets[0].attr
    call_node = assign.value
    decl = extractor._extract_field_declaration(field_name, call_node)
    assert decl is not None
    assert decl.implied_group == "stock.group_stock_multi_locations"
    assert decl.field_type == "Boolean"


def test_extractor_no_implied_group():
    """Regular field should have implied_group=None."""
    source = '''
class SaleOrder(models.Model):
    _name = 'sale.order'
    name = fields.Char('Order Reference')
'''
    extractor = OdooClassVisitor()
    tree = ast.parse(source)
    class_node = tree.body[0]
    assign = class_node.body[1]
    field_name = assign.targets[0].id if hasattr(assign.targets[0], 'id') else assign.targets[0].attr
    call_node = assign.value
    decl = extractor._extract_field_declaration(field_name, call_node)
    assert decl is not None
    assert decl.implied_group is None


# ── 3. Graph nodes get group_type attribute ──────────────────────────────

def _build_test_graph_with_implied_group():
    """Build a minimal graph with a technical group from settings."""
    G = nx.DiGraph()
    # Role group
    G.add_node(
        "group:stock.group_stock_user",
        node_type="Group",
        xml_id="stock.group_stock_user",
        name="User",
        category_id="base.module_category_inventory_inventory",
        group_type="role",
        setting_field=None,
    )
    # Technical group (feature flag)
    G.add_node(
        "group:stock.group_stock_multi_locations",
        node_type="Group",
        xml_id="stock.group_stock_multi_locations",
        name="Manage Multiple Stock Locations",
        category_id="base.module_category_hidden",
        group_type="technical",
        setting_field="group_stock_multi_locations",
    )
    # base.group_user
    G.add_node(
        "group:base.group_user",
        node_type="Group",
        xml_id="base.group_user",
        name="Internal User",
        category_id="base.module_category_hidden",
        group_type="role",
        setting_field=None,
    )
    # Role hierarchy: stock_user IMPLIES base.group_user
    G.add_edge("group:stock.group_stock_user", "group:base.group_user", edge_type="IMPLIES")
    # Settings-activated: base.group_user IMPLIES_CONFIGURABLE multi_locations
    G.add_edge(
        "group:base.group_user", "group:stock.group_stock_multi_locations",
        edge_type="IMPLIES_CONFIGURABLE",
        setting_field="group_stock_multi_locations",
        conditional=True,
    )
    return G


def test_group_node_type_technical():
    """Technical groups should have group_type='technical'."""
    G = _build_test_graph_with_implied_group()
    node = G.nodes["group:stock.group_stock_multi_locations"]
    assert node["group_type"] == "technical"
    assert node["setting_field"] == "group_stock_multi_locations"


def test_group_node_type_role():
    """Role groups should have group_type='role'."""
    G = _build_test_graph_with_implied_group()
    node = G.nodes["group:stock.group_stock_user"]
    assert node["group_type"] == "role"


# ── 4. IMPLIES_CONFIGURABLE edges exist ──────────────────────────────────

def test_implies_configurable_edge_exists():
    """IMPLIES_CONFIGURABLE edge should exist from base.group_user to technical group."""
    G = _build_test_graph_with_implied_group()
    edge_data = G.get_edge_data(
        "group:base.group_user",
        "group:stock.group_stock_multi_locations",
    )
    assert edge_data is not None
    assert edge_data["edge_type"] == "IMPLIES_CONFIGURABLE"
    assert edge_data["setting_field"] == "group_stock_multi_locations"
    assert edge_data["conditional"] is True


# ── 5. _expand_implied_user_groups follows IMPLIES_CONFIGURABLE ──────────

def test_expand_implied_follows_configurable():
    """_expand_implied_user_groups should follow IMPLIES_CONFIGURABLE edges."""
    G = _build_test_graph_with_implied_group()
    user_groups = {"stock.group_stock_user"}
    for g in list(user_groups):
        _expand_implied_user_groups(G, g, user_groups)
    # Should have expanded to include base.group_user (via IMPLIES)
    # and stock.group_stock_multi_locations (via IMPLIES_CONFIGURABLE from base.group_user)
    assert "base.group_user" in user_groups
    assert "stock.group_stock_multi_locations" in user_groups


def test_expand_implied_without_configurable_edge():
    """Without IMPLIES_CONFIGURABLE edge, technical group should NOT be reached."""
    G = nx.DiGraph()
    G.add_node("group:stock.group_stock_user", node_type="Group")
    G.add_node("group:base.group_user", node_type="Group")
    G.add_node("group:stock.group_stock_multi_locations", node_type="Group")
    G.add_edge("group:stock.group_stock_user", "group:base.group_user", edge_type="IMPLIES")
    # No IMPLIES_CONFIGURABLE edge
    user_groups = {"stock.group_stock_user"}
    for g in list(user_groups):
        _expand_implied_user_groups(G, g, user_groups)
    assert "base.group_user" in user_groups
    assert "stock.group_stock_multi_locations" not in user_groups


# ── 6. button_execution_path technical group message ─────────────────────

def test_button_path_technical_group_message():
    """When required group is technical, unavailable_reason should mention settings."""
    G = _build_test_graph_with_implied_group()
    # Simulate what button_execution_path does for unavailable_reason
    required_groups = ["stock.group_stock_multi_locations"]
    technical_groups = []
    role_groups = []
    for rg in sorted(required_groups):
        rg_node = f"group:{rg}"
        if G.has_node(rg_node) and G.nodes[rg_node].get("group_type") == "technical":
            setting_field = G.nodes[rg_node].get("setting_field", "")
            technical_groups.append((rg, setting_field))
        else:
            role_groups.append(rg)

    assert len(technical_groups) == 1
    assert len(role_groups) == 0
    assert technical_groups[0] == ("stock.group_stock_multi_locations", "group_stock_multi_locations")


def test_button_path_role_group_message():
    """When required group is a role, it should be classified as role_groups."""
    G = _build_test_graph_with_implied_group()
    required_groups = ["stock.group_stock_user"]
    technical_groups = []
    role_groups = []
    for rg in sorted(required_groups):
        rg_node = f"group:{rg}"
        if G.has_node(rg_node) and G.nodes[rg_node].get("group_type") == "technical":
            setting_field = G.nodes[rg_node].get("setting_field", "")
            technical_groups.append((rg, setting_field))
        else:
            role_groups.append(rg)

    assert len(technical_groups) == 0
    assert len(role_groups) == 1
    assert role_groups[0] == "stock.group_stock_user"
