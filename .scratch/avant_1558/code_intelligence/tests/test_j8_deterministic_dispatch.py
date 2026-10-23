"""Tests for graph-level server-action lookup used by tool analysis."""

import networkx as nx
from code_intelligence.agent.tools.helpers import find_server_action_nodes


def test_find_server_action_nodes_helper():
    """Verify standalone helper correctly finds ServerAction nodes targeting a model."""
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node(
        "server_action:custom_automation_traps.action_auto_validate",
        node_type="ServerAction",
        xml_id="custom_automation_traps.action_auto_validate",
        model_id="account.move",
        code="record.sudo().action_valider_avoir()",
    )
    G.add_edge(
        "server_action:custom_automation_traps.action_auto_validate",
        "model:account.move",
        edge_type="TARGETS_MODEL",
    )

    sa_nodes = find_server_action_nodes(G, "account.move")
    assert len(sa_nodes) == 1
    assert sa_nodes[0][0] == "server_action:custom_automation_traps.action_auto_validate"

    # Model without server actions returns empty list
    assert find_server_action_nodes(G, "purchase.order") == []
