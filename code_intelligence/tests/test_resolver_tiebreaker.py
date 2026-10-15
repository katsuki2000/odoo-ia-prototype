import networkx as nx

from code_intelligence.agent.matching import _find_exact_technical_module_mentions
from code_intelligence.agent.resolution import candidates as candidate_selection
from code_intelligence.agent.resolver import (
    _arbitration_candidates,
    _build_arbitration_prompt,
    _candidate_contexts,
    _deterministic_tiebreak,
)


def test_standalone_unknown_module_mention_selects_its_declared_candidate():
    graph = nx.DiGraph()
    graph.add_node("module:project_inventory")
    graph.add_node("module:project_accounting")
    graph.add_node("model:project_inventory.order", node_type="Model")
    graph.add_node("model:project_accounting.order", node_type="Model")
    graph.add_edge(
        "model:project_inventory.order",
        "module:project_inventory",
        edge_type="DEFINED_IN",
    )
    graph.add_edge(
        "model:project_accounting.order",
        "module:project_accounting",
        edge_type="DEFINED_IN",
    )

    winner = _deterministic_tiebreak(
        "does the project_inventory module handle asset loans?",
        [("project_inventory.order", 90.0), ("project_accounting.order", 90.0)],
        graph,
    )

    assert winner == "project_inventory.order"


def test_group_xmlid_prefix_does_not_break_a_model_tie():
    graph = nx.DiGraph()
    for module, model in (("base", "res.partner"), ("sale", "sale.order")):
        graph.add_node(f"module:{module}")
        graph.add_node(f"model:{model}", node_type="Model")
        graph.add_edge(
            f"model:{model}", f"module:{module}",
            edge_type="DEFINED_IN", role="declares",
        )

    winner = _deterministic_tiebreak(
        "who can view base.group_portal and sales_team.group_sale_salesman?",
        [("res.partner", 90.0), ("sale.order", 90.0)],
        graph,
    )

    assert winner is None


def test_generic_model_segment_does_not_break_a_real_tie():
    graph = nx.DiGraph()
    for module, model in (
        ("sale", "sale.order"),
        ("purchase", "purchase.order"),
    ):
        graph.add_node(f"module:{module}")
        graph.add_node(f"model:{model}", node_type="Model")
        graph.add_edge(f"model:{model}", f"module:{module}", edge_type="DEFINED_IN")

    winner = _deterministic_tiebreak(
        "who can see all orders?",
        [("sale.order", 90.0), ("purchase.order", 90.0)],
        graph,
    )

    assert winner is None


def test_extension_module_does_not_outvote_the_declaring_module():
    graph = nx.DiGraph()
    graph.add_node("module:base")
    graph.add_node("module:stock")
    graph.add_node("model:res.partner", node_type="Model")
    graph.add_node("model:stock.picking", node_type="Model")
    graph.add_edge(
        "model:res.partner", "module:base", edge_type="DEFINED_IN", role="declares",
    )
    graph.add_edge(
        "model:res.partner", "module:stock", edge_type="DEFINED_IN", role="extends",
    )
    graph.add_edge(
        "model:stock.picking", "module:stock", edge_type="DEFINED_IN", role="declares",
    )

    winner = _deterministic_tiebreak(
        "check stock.group_user and stock transfer visibility",
        [("res.partner", 90.0), ("stock.picking", 90.0)],
        graph,
    )

    assert winner == "stock.picking"


def test_module_xmlid_prefix_is_not_an_explicit_module_mention():
    graph = nx.DiGraph()
    graph.add_node("module:sales_team", node_type="Module", name="sales_team")

    modules = _find_exact_technical_module_mentions(
        "Who can view sales_team.group_sale_salesman?", graph,
    )

    assert modules == []


def test_arbitration_context_comes_from_instance_labels_and_declaring_modules():
    graph = nx.DiGraph()
    graph.add_node("module:sale", node_type="Module")
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        description="Sales Order",
        business_labels=[
            {"label": "Commande client", "language": "fr_FR"},
            {"label": "Sales Order", "language": "en_US"},
        ],
    )
    graph.add_edge(
        "model:sale.order", "module:sale", edge_type="DEFINED_IN", role="declares",
    )

    contexts = _candidate_contexts(graph, ["sale.order"])

    assert contexts == {
        "sale.order": "labels: Commande client, Sales Order; modules: sale",
    }


def test_arbitration_prompt_includes_graph_context_for_closed_candidates():
    prompt = _build_arbitration_prompt(
        "Ou gerer les commandes client ?",
        ["sale.order"],
        {"sale.order": "labels: Commande client; modules: sale"},
    )

    assert "- sale.order — labels: Commande client; modules: sale" in prompt
    assert "purchase.order" not in prompt


def test_arbitration_candidates_do_not_call_embeddings_without_llm(monkeypatch):
    graph = nx.DiGraph()
    graph.add_node("model:sale.order", node_type="Model", description="Sales Order")
    monkeypatch.setattr(
        candidate_selection,
        "retrieve_semantic_model_candidates",
        lambda *_args: (_ for _ in ()).throw(AssertionError("embeddings must not run")),
    )

    candidates = _arbitration_candidates(
        "sales order",
        graph,
        "en",
        False,
        False,
        [("sale.order", 100.0)],
    )

    assert candidates == ["sale.order"]
