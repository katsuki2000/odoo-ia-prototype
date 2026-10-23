"""
code_intelligence/tests/test_bloc17_navigation_path.py

Bloc 17, Etage 1 (todo/plan.md, Jour 2-3): tests for
describe_navigation_path() -- menu -> action -> vue -> bouton resolution
for "comment faire pour X" questions. Covers the 3 verdicts defined in
todo/bloc17_jour1_perimetre.md: FOUND (real path), EMPTY ("aucun chemin
UI"), NOT_FOUND (model itself unresolved).
"""

import networkx as nx

from code_intelligence.rules.common import QueryStatus
from code_intelligence.rules.navigation import describe_navigation_path
from core.evidence.evidence import Evidence


def _build_menu_graph(model_name="custom.purchase.request", with_button=False, menu_groups=None):
    """
    Sales > Vente > Demandes d'achat (3-level breadcrumb) -- menu opens
    model_name via an OPENS_MODEL edge, same edge convention as
    code_intelligence/graph/ui_nodes.py::add_menu_nodes.
    """
    G = nx.DiGraph()
    G.add_node(f"model:{model_name}", node_type="Model", name=model_name)

    G.add_node("menu:base.menu_root", node_type="Menu", name="Ventes", xml_id="base.menu_root",
                sequence=10, filepath="", groups=[])
    G.add_node("menu:sale.menu_sale_config", node_type="Menu", name="Configuration",
                xml_id="sale.menu_sale_config", sequence=20, filepath="", groups=[])
    G.add_edge("menu:sale.menu_sale_config", "menu:base.menu_root", edge_type="CHILD_OF")

    leaf_groups = menu_groups or []
    G.add_node("menu:ext_purchase_request.menu_requests", node_type="Menu",
                name="Demandes d'achat", xml_id="ext_purchase_request.menu_requests",
                sequence=30, filepath="/repo/ext_purchase_request/views/menu.xml",
                groups=leaf_groups)
    G.add_edge("menu:ext_purchase_request.menu_requests", "menu:sale.menu_sale_config",
                edge_type="CHILD_OF")
    G.add_edge("menu:ext_purchase_request.menu_requests", f"model:{model_name}",
                edge_type="OPENS_MODEL", via="act_window")

    if with_button:
        G.add_node(f"method:{model_name}.action_submit", node_type="Method",
                    name="action_submit", model=model_name)
        G.add_node(f"state:{model_name}.draft", node_type="WorkflowState",
                    model=model_name, state_value="draft")
        G.add_node(f"state:{model_name}.submitted", node_type="WorkflowState",
                    model=model_name, state_value="submitted")
        G.add_edge(f"state:{model_name}.draft", f"state:{model_name}.submitted",
                    edge_type="TRANSITIONS_VIA", method_name="action_submit",
                    label_bouton="Soumettre", groupe_requis=["ext_purchase_request.group_requester"])

    return G


def test_not_found_when_model_absent():
    G = nx.DiGraph()
    res = describe_navigation_path(G, "unknown.model")
    assert res.status == QueryStatus.NOT_FOUND
    assert "was not found" in res.summary_text


def test_empty_when_model_exists_but_no_menu_opens_it():
    """The 'aucun chemin UI' verdict -- confirmed real on ext_purchase_request
    /asset_loan in todo/bloc17_jour1_perimetre.md."""
    G = nx.DiGraph()
    G.add_node("model:custom.asset.loan", node_type="Model", name="custom.asset.loan")
    res = describe_navigation_path(G, "custom.asset.loan")
    assert res.status == QueryStatus.EMPTY
    assert "Aucun chemin d'interface" in res.summary_text
    assert len(res.evidence) == 1
    assert res.evidence[0].value is None


def test_found_builds_full_breadcrumb_root_to_leaf():
    G = _build_menu_graph()
    res = describe_navigation_path(G, "custom.purchase.request")
    assert res.status == QueryStatus.FOUND
    assert res.menu_breadcrumb == ["Ventes", "Configuration", "Demandes d'achat"]
    assert res.menu_xml_id == "ext_purchase_request.menu_requests"
    assert all(isinstance(e, Evidence) for e in res.evidence)


def test_found_prefers_unrestricted_menu_over_restricted_one():
    G = _build_menu_graph(menu_groups=["ext_purchase_request.group_requester"])
    # A second, unrestricted menu also opens the same model.
    G.add_node("menu:ext_purchase_request.menu_requests_alt", node_type="Menu",
                name="Demandes d'achat (public)", xml_id="ext_purchase_request.menu_requests_alt",
                sequence=5, filepath="", groups=[])
    G.add_edge("menu:ext_purchase_request.menu_requests_alt", "model:custom.purchase.request",
                edge_type="OPENS_MODEL", via="act_window")

    res = describe_navigation_path(G, "custom.purchase.request")
    assert res.status == QueryStatus.FOUND
    assert res.menu_xml_id == "ext_purchase_request.menu_requests_alt"
    assert res.menu_groups == []


def test_found_menu_restricted_and_user_not_in_group_is_unavailable():
    G = _build_menu_graph(menu_groups=["ext_purchase_request.group_requester"])
    res = describe_navigation_path(
        G, "custom.purchase.request", user_groups=["base.group_user"]
    )
    assert res.status == QueryStatus.FOUND
    assert res.available_to_requester is False
    assert "NON DISPONIBLE POUR LE DEMANDEUR" in res.summary_text
    assert res.unavailable_reason
    assert any(e.source.startswith("menu:") and e.value is False for e in res.evidence)


def test_found_menu_unrestricted_and_no_user_groups_leaves_availability_none():
    G = _build_menu_graph()
    res = describe_navigation_path(G, "custom.purchase.request")
    assert res.available_to_requester is None
    assert res.unavailable_reason == ""


def test_found_with_button_delegates_to_button_execution_path():
    G = _build_menu_graph(with_button=True)
    res = describe_navigation_path(G, "custom.purchase.request", button_label_or_name="Soumettre")
    assert res.status == QueryStatus.FOUND
    assert res.button_result is not None
    assert res.button_result.method_name == "action_submit"
    assert any("Soumettre" in s for s in res.execution_steps)
    # Evidence from both the menu and the delegated button_execution_path are merged.
    assert len(res.evidence) >= 2


def test_found_combines_menu_and_button_required_groups_for_availability():
    G = _build_menu_graph(with_button=True, menu_groups=["ext_purchase_request.group_requester"])
    res = describe_navigation_path(
        G, "custom.purchase.request", button_label_or_name="Soumettre",
        user_groups=["base.group_user"],
    )
    assert res.available_to_requester is False
