from types import SimpleNamespace

import networkx as nx
import pytest

from code_intelligence.extractor.xml import parse_actions_from_xml
from code_intelligence.graph.nodes import ResolvedSymbolRegistry, add_menu_nodes
from code_intelligence.graph.workflow_extraction import domain_admits_any_state
from code_intelligence.rules.navigation import _menus_opening_model

PURCHASE_ONLY = "[('state', 'in', ('purchase', 'done'))]"
NOT_QUOTATION = "[('state', 'not in', ('draft', 'sent', 'cancel'))]"


@pytest.mark.parametrize(
    "domain, states, expected",
    [
        (PURCHASE_ONLY, ["draft", "sent"], False),
        (PURCHASE_ONLY, ["draft", "purchase"], True),
        (NOT_QUOTATION, ["draft", "sent"], False),
        (NOT_QUOTATION, ["sale"], True),
        ("[('state', '=', 'draft')]", ["draft"], True),
        ("[('state', '!=', 'draft')]", ["draft"], False),
        ("[]", ["draft"], True),
        ("", ["draft"], True),
        (PURCHASE_ONLY, [], True),
        ("[('state', 'in', states)]", ["draft"], True),
        ("['|', ('state', '=', 'a'), ('state', '=', 'b')]", ["draft"], True),
        ("[('partner_id', '=', 1)]", ["draft"], True),
        ("[('partner_id', '=', 1), ('state', 'in', ('done',))]", ["draft"], False),
    ],
)
def test_domain_admits_any_state(domain, states, expected):
    assert domain_admits_any_state(domain, states) is expected


def _graph_with_two_menus():
    graph = nx.DiGraph()
    graph.add_node("model:purchase.order", node_type="Model")
    graph.add_node("menu:purchase.menu_orders", node_type="Menu", sequence=0, groups=[],
                   action_domain=PURCHASE_ONLY)
    graph.add_node("menu:purchase.menu_rfq", node_type="Menu", sequence=6, groups=[],
                   action_domain="[]")
    for menu in ("menu:purchase.menu_orders", "menu:purchase.menu_rfq"):
        graph.add_edge(menu, "model:purchase.order", edge_type="OPENS_MODEL")
    return graph


def test_menu_whose_domain_excludes_origin_states_is_not_chosen():
    graph = _graph_with_two_menus()
    chosen = [menu for menu, _ in _menus_opening_model(graph, "purchase.order", ["draft", "sent"])]
    assert chosen == ["menu:purchase.menu_rfq"]


def test_sequence_order_is_kept_when_states_are_unknown():
    graph = _graph_with_two_menus()
    chosen = [menu for menu, _ in _menus_opening_model(graph, "purchase.order")]
    assert chosen == ["menu:purchase.menu_orders", "menu:purchase.menu_rfq"]


def test_all_menus_are_kept_when_none_admits_the_states():
    graph = _graph_with_two_menus()
    graph.nodes["menu:purchase.menu_rfq"]["action_domain"] = PURCHASE_ONLY
    chosen = _menus_opening_model(graph, "purchase.order", ["draft"])
    assert len(chosen) == 2


def _registry(**actions):
    # A real registry: a technical model name resolves only when it is in `models` (no guessing).
    return ResolvedSymbolRegistry(actions=actions, models={"purchase.order": []})


def _module(*menus):
    return SimpleNamespace(menuitems=list(menus))


def _menu(xml_id, name="", action="", parent=""):
    return SimpleNamespace(xml_id=xml_id, name=name, sequence=1, filepath="", action=action,
                           groups=[], parent=parent)


def test_menu_without_name_takes_the_action_name_and_domain():
    action = SimpleNamespace(name="Requests for Quotation", res_model="purchase.order",
                             domain="[]")
    graph = nx.DiGraph()
    add_menu_nodes(graph, _registry(**{"purchase.rfq_action": action}),
                   {"purchase": _module(_menu("menu_rfq", action="rfq_action"))})
    node = graph.nodes["menu:purchase.menu_rfq"]
    assert node["name"] == "Requests for Quotation"
    assert node["action_domain"] == "[]"


def test_menu_own_name_wins_over_action_name():
    action = SimpleNamespace(name="Action name", res_model="purchase.order", domain="")
    graph = nx.DiGraph()
    add_menu_nodes(graph, _registry(**{"purchase.act": action}),
                   {"purchase": _module(_menu("menu_x", name="Menu name", action="act"))})
    assert graph.nodes["menu:purchase.menu_x"]["name"] == "Menu name"


def test_menu_without_action_has_empty_domain_and_name_kept():
    graph = nx.DiGraph()
    add_menu_nodes(graph, _registry(), {"purchase": _module(_menu("menu_root", name="Purchase"))})
    node = graph.nodes["menu:purchase.menu_root"]
    assert node["name"] == "Purchase"
    assert node["action_domain"] == ""


ACTIONS_XML = """<odoo>
  <record id="action_text" model="ir.actions.act_window">
    <field name="name">Text domain</field>
    <field name="res_model">purchase.order</field>
    <field name="domain">[('state', 'in', ('purchase', 'done'))]</field>
  </record>
  <record id="action_eval" model="ir.actions.act_window">
    <field name="name">Eval domain</field>
    <field name="res_model">purchase.order</field>
    <field name="domain" eval="[('state', '=', 'draft')]"/>
  </record>
  <record id="action_none" model="ir.actions.act_window">
    <field name="name">No domain</field>
    <field name="res_model">purchase.order</field>
  </record>
</odoo>"""


def test_action_domain_is_extracted_from_text_and_eval(tmp_path):
    xml_file = tmp_path / "actions.xml"
    xml_file.write_text(ACTIONS_XML, encoding="utf-8")
    domains = {action.xml_id: action.domain for action in parse_actions_from_xml(xml_file)}
    assert domains["action_text"] == PURCHASE_ONLY
    assert domains["action_eval"] == "[('state', '=', 'draft')]"
    assert domains["action_none"] == ""


def _module_with_actions(*actions):
    return SimpleNamespace(menuitems=[], actions=list(actions))


def _window_action(xml_id, res_model, name=""):
    return SimpleNamespace(xml_id=xml_id, res_model=res_model, name=name)


def test_window_action_without_menu_is_recorded_on_the_model():
    from code_intelligence.graph.nodes import add_window_action_refs

    graph = nx.DiGraph()
    graph.add_node("model:custom.request")
    add_window_action_refs(
        graph,
        {"custom": _module_with_actions(_window_action("act_request", "custom.request", "Requests"))},
    )
    assert graph.nodes["model:custom.request"]["window_actions"] == [
        {"xml_id": "custom.act_request", "name": "Requests", "module": "custom"},
    ]


def test_window_action_targeting_an_unknown_model_is_ignored():
    from code_intelligence.graph.nodes import add_window_action_refs

    graph = nx.DiGraph()
    add_window_action_refs(graph, {"custom": _module_with_actions(_window_action("a", "missing.model"))})
    assert not graph.nodes


def test_navigation_reports_the_orphan_window_action():
    from code_intelligence.rules.navigation import describe_navigation_path

    graph = nx.DiGraph()
    graph.add_node("model:custom.request", node_type="Model", window_actions=[
        {"xml_id": "custom.act_request", "name": "Requests", "module": "custom"},
    ])
    result = describe_navigation_path(graph, "custom.request")
    assert "custom.act_request" in result.summary_text
    assert "aucun menu" in result.summary_text.lower()
