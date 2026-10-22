"""
code_intelligence/tests/test_bloc17_jour4_navigation_path_tool_wiring.py

Bloc 17, Etage 1, Jour 4 (todo/contexte.txt section 645-646): the @tool
wrapper for describe_navigation_path() in ci_agent_node/agent_tools.py --
LangChain contract (still returns a plain str) + Bloc B2 record_evidence()
wiring, same convention as every other composite tool in this file
(who_has_access_to, button_execution_path, etc.). The deterministic logic
itself (3 verdicts, breadcrumb, button delegation) is already covered by
code_intelligence/tests/test_bloc17_navigation_path.py -- not retested here.
"""

import networkx as nx
import pytest

from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tools.helpers import set_graph_ref
from code_intelligence.agent.tools.structure import describe_navigation_path
from core.evidence.evidence_collector import (
    _turn_evidence_ctx,
    start_evidence_collection,
    collect_and_clear_evidence,
)


@pytest.fixture(autouse=True)
def _reset_turn_evidence_ctx():
    _turn_evidence_ctx.set(None)
    yield
    _turn_evidence_ctx.set(None)


def _build_graph_with_menu(model_name="custom.purchase.request"):
    G = nx.DiGraph()
    G.add_node(f"model:{model_name}", node_type="Model", name=model_name)
    G.add_node(
        "menu:custom_purchase_request.menu_requests", node_type="Menu",
        name="Demandes d'achat", xml_id="custom_purchase_request.menu_requests",
        sequence=10, filepath="/repo/custom_purchase_request/views/menu.xml", groups=[],
    )
    G.add_edge(
        "menu:custom_purchase_request.menu_requests", f"model:{model_name}",
        edge_type="OPENS_MODEL", via="act_window",
    )
    return G


def test_tool_is_registered_in_all_ci_tools():
    names = [t.name for t in ALL_CI_TOOLS]
    assert "describe_navigation_path" in names


def test_wrapper_returns_plain_string_found_case():
    G = _build_graph_with_menu()
    set_graph_ref(G)
    result = describe_navigation_path.invoke({"model_name": "custom.purchase.request"})
    assert isinstance(result, str)
    assert "custom.purchase.request" in result
    assert "Demandes d'achat" in result


def test_wrapper_returns_plain_string_not_found_case():
    G = nx.DiGraph()  # empty graph -- model absent
    set_graph_ref(G)
    result = describe_navigation_path.invoke({"model_name": "custom.unknown.model"})
    assert isinstance(result, str)
    assert "custom.unknown.model" in result


def test_wrapper_records_evidence_when_turn_active():
    G = _build_graph_with_menu()
    set_graph_ref(G)

    start_evidence_collection()
    describe_navigation_path.invoke({"model_name": "custom.purchase.request"})
    dossier = collect_and_clear_evidence()

    assert len(dossier) >= 1, (
        "describe_navigation_path always attaches at least one Evidence "
        "for the menu->model resolution itself (FOUND or EMPTY verdict, "
        "cf. navigation_path.py) -- must reach the dossier via record_evidence()."
    )


def test_wrapper_without_active_turn_does_not_raise():
    G = _build_graph_with_menu()
    set_graph_ref(G)
    # No start_evidence_collection() -- must still work (tool contract
    # untouched), evidence just dropped with a warning (Bloc B2 design).
    result = describe_navigation_path.invoke({"model_name": "custom.purchase.request"})
    assert isinstance(result, str)
