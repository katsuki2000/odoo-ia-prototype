import networkx as nx


def build_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    for model in ("account.move", "mail.thread", "res.users"):
        graph.add_node(f"model:{model}", node_type="Model", name=model)
    graph.add_edge("model:account.move", "model:mail.thread", edge_type="EXTENDS")
    for model, method in (
        ("account.move", "action_post"),
        ("mail.thread", "message_post"),
        ("res.users", "has_group"),
    ):
        graph.add_node(f"method:{model}.{method}", node_type="Method", name=method, model=model)
    graph.add_node("group:account.group_account_manager", node_type="Group", xml_id="account.group_account_manager")
    return graph
