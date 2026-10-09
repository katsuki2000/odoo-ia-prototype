"""Section 1199: nested <menuitem> parents and effective menu visibility."""
from pathlib import Path

import networkx as nx

from code_intelligence.extractor.xml import parse_menuitems_from_xml
from code_intelligence.rules.navigation import (
    _menu_breadcrumb,
    _menu_chain_group_requirements,
    describe_navigation_path,
)

NESTED_XML = """<?xml version="1.0"?>
<odoo>
  <menuitem id="menu_root" name="Invoicing" groups="mod.grp_a,mod.grp_b">
    <menuitem id="menu_mid" name="Customers">
      <menuitem id="menu_leaf" action="act" sequence="1"/>
      <menuitem id="menu_explicit" action="act2" parent="other_parent"/>
    </menuitem>
  </menuitem>
  <menuitem id="menu_flat" name="Flat" parent="menu_root"/>
</odoo>
"""


def _parse(tmp_path: Path):
    f = tmp_path / "menus.xml"
    f.write_text(NESTED_XML, encoding="utf-8")
    return {m.xml_id: m for m in parse_menuitems_from_xml(f)}


def test_nested_menuitem_takes_enclosing_menu_as_parent(tmp_path):
    menus = _parse(tmp_path)
    assert menus["menu_root"].parent == ""
    assert menus["menu_mid"].parent == "menu_root"
    assert menus["menu_leaf"].parent == "menu_mid"


def test_explicit_parent_attribute_wins_over_nesting(tmp_path):
    menus = _parse(tmp_path)
    assert menus["menu_explicit"].parent == "other_parent"
    assert menus["menu_flat"].parent == "menu_root"


def _graph():
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model")
    G.add_node("menu:m.root", node_type="Menu", xml_id="m.root", name="Invoicing",
               groups=["m.grp_a", "m.grp_b"], sequence=1)
    G.add_node("menu:m.mid", node_type="Menu", xml_id="m.mid", name="Customers", groups=[], sequence=1)
    G.add_node("menu:m.leaf", node_type="Menu", xml_id="m.leaf", name="Invoices", groups=[],
               sequence=1, action_domain="[]", filepath="")
    G.add_edge("menu:m.leaf", "menu:m.mid", edge_type="CHILD_OF")
    G.add_edge("menu:m.mid", "menu:m.root", edge_type="CHILD_OF")
    G.add_edge("menu:m.leaf", "model:account.move", edge_type="OPENS_MODEL")
    for g in ("m.grp_a", "m.grp_b", "m.other"):
        G.add_node(f"group:{g}", node_type="Group", xml_id=g, name=g)
    return G


def test_breadcrumb_and_requirements_walk_the_whole_chain():
    G = _graph()
    assert _menu_breadcrumb(G, "menu:m.leaf") == ["Invoicing", "Customers", "Invoices"]
    reqs, length = _menu_chain_group_requirements(G, "menu:m.leaf")
    assert length == 3
    assert reqs == [("m.root", ["m.grp_a", "m.grp_b"])]


def test_ancestor_restriction_is_reported_not_hidden():
    r = describe_navigation_path(_graph(), "account.move", "", user_groups=None)
    assert r.menu_groups == ["m.grp_a", "m.grp_b"]
    steps = " ".join(r.execution_steps)
    assert "no group restriction on the menu itself" not in steps
    assert "m.root" in steps and "EACH" in steps


def test_requester_availability_follows_the_ancestor_groups():
    G = _graph()
    assert describe_navigation_path(G, "account.move", "", user_groups=["m.grp_a"]).available_to_requester is True
    denied = describe_navigation_path(G, "account.move", "", user_groups=["m.other"])
    assert denied.available_to_requester is False
    assert "m.grp_a" in denied.unavailable_reason


def test_chain_without_any_group_says_so_for_parents_too():
    G = _graph()
    G.nodes["menu:m.root"]["groups"] = []
    r = describe_navigation_path(G, "account.move", "", user_groups=[])
    assert "or its parent menus" in " ".join(r.execution_steps)
    assert r.available_to_requester is True
