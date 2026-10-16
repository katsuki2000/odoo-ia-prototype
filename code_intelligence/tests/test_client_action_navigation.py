"""Client actions (ir.actions.client) are extracted, linked to their menu and reported by the navigation tool."""
from pathlib import Path

import networkx as nx

from code_intelligence.extractor.xml import parse_actions_from_xml, parse_menuitems_from_xml
from code_intelligence.graph.nodes import ParsedModule, add_menu_nodes
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.rules.common import QueryStatus
from code_intelligence.rules.navigation import MAX_CLIENT_ACTION_MENUS, describe_navigation_path

DASHBOARD_XML = """<?xml version="1.0"?>
<odoo>
  <record id="client_action" model="ir.actions.client">
    <field name="name">Dashboards</field>
    <field name="tag">action_dashboard</field>
  </record>
  <record id="window_action" model="ir.actions.act_window">
    <field name="name">Groups</field>
    <field name="res_model">dash.group</field>
  </record>
  <menuitem id="menu_root" name="Dashboards" action="client_action" sequence="37"/>
  <menuitem id="menu_groups" name="Groups" parent="menu_root" action="window_action"/>
</odoo>
"""


class _Manifest:
    depends = []
    filepath = "dash/__manifest__.py"


def _module(tmp_path: Path) -> ParsedModule:
    xml = tmp_path / "menus.xml"
    xml.write_text(DASHBOARD_XML, encoding="utf-8")
    module = ParsedModule(manifest=_Manifest())
    module.actions = parse_actions_from_xml(xml)
    module.menuitems = parse_menuitems_from_xml(xml)
    return module


def test_client_action_is_extracted_with_its_tag(tmp_path):
    actions = {a.xml_id: a for a in _module(tmp_path).actions}
    assert actions["client_action"].action_type == "client"
    assert actions["client_action"].tag == "action_dashboard"
    assert actions["client_action"].res_model == ""
    assert actions["window_action"].action_type == "act_window"


def test_menu_node_records_the_action_type_and_gets_no_model_edge(tmp_path):
    modules = {"dash": _module(tmp_path)}
    G = nx.DiGraph()
    add_menu_nodes(G, build_module_symbol_registry(modules), modules)
    root = G.nodes["menu:dash.menu_root"]
    assert (root["action_type"], root["action_tag"]) == ("client", "action_dashboard")
    assert G.nodes["menu:dash.menu_groups"]["action_type"] == "act_window"
    assert not [edge for _, _, edge in G.out_edges("menu:dash.menu_root", data=True) if edge["edge_type"] == "OPENS_MODEL"]


def _graph(menuCount=1):
    G = nx.DiGraph()
    G.add_node("model:dash.board", node_type="Model")
    G.add_node("module:dash", node_type="Module")
    G.add_node("module:other", node_type="Module")
    G.add_edge("model:dash.board", "module:dash", edge_type="DEFINED_IN", role="declares")
    for index in range(menuCount):
        G.add_node(f"menu:dash.menu_{index}", node_type="Menu", xml_id=f"dash.menu_{index}", name="Dashboards",
                   module="dash", action_ref="client_action", action_type="client", action_tag="action_dashboard",
                   groups=[], sequence=index)
    G.add_node("menu:other.menu", node_type="Menu", xml_id="other.menu", name="Elsewhere", module="other",
               action_type="client", groups=[], sequence=1)
    return G


def test_model_without_menu_reports_client_action_menu_of_its_module():
    result = describe_navigation_path(_graph(), "dash.board")
    assert result.status == QueryStatus.EMPTY
    assert "dash.menu_0" in result.summary_text
    assert "action_dashboard" in result.summary_text
    assert "ne prouve pas" in result.summary_text
    assert "other.menu" not in result.summary_text
    assert any("dash.menu_0" in evidence.claim for evidence in result.evidence)


def test_client_action_menus_are_bounded():
    result = describe_navigation_path(_graph(menuCount=MAX_CLIENT_ACTION_MENUS + 3), "dash.board")
    assert result.summary_text.count("action client 'action_dashboard'") == MAX_CLIENT_ACTION_MENUS


def test_model_without_any_client_action_menu_keeps_the_plain_verdict():
    G = _graph()
    G.remove_nodes_from(["menu:dash.menu_0", "menu:other.menu"])
    result = describe_navigation_path(G, "dash.board")
    assert result.status == QueryStatus.EMPTY
    assert "action client" not in result.summary_text
