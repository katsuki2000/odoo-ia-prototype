import networkx as nx

from code_intelligence.rules.access_evaluator import who_has_access_to
from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.rules.model_suggestions import (
    RETRY_INSTRUCTION,
    closest_models,
    model_not_found_message,
)


def _graph(*model_names):
    G = nx.DiGraph()
    for name in model_names:
        G.add_node(f"model:{name}", node_type="Model", name=name)
    G.add_node("group:purchase.group_purchase_manager", node_type="Group")
    return G


PURCHASE_GRAPH_MODELS = (
    "purchase.order",
    "purchase.order.line",
    "purchase.report",
    "sale.order",
    "account.move",
    "res.partner",
)


def test_unknown_model_suggests_the_closest_indexed_models():
    G = _graph(*PURCHASE_GRAPH_MODELS)
    candidates = closest_models(G, "purchase.request")
    assert "purchase.order" in candidates
    assert "res.partner" not in candidates
    assert "account.move" not in candidates


def test_rare_token_outranks_common_prefix():
    G = _graph("account.move", "account.payment", "account.tax", "account.journal", "stock.picking.batch")
    assert closest_models(G, "stock.batch", limit=1) == ["stock.picking.batch"]


def test_no_shared_token_gives_no_candidate_and_keeps_plain_message():
    G = _graph(*PURCHASE_GRAPH_MODELS)
    message = model_not_found_message(G, "zzz.unknown")
    assert NOT_FOUND_MARKER in message
    assert "Closest" not in message
    assert RETRY_INSTRUCTION not in message


def test_message_keeps_marker_and_typo_wording_with_suggestions():
    G = _graph(*PURCHASE_GRAPH_MODELS)
    message = model_not_found_message(G, "purchase.request")
    assert NOT_FOUND_MARKER in message
    assert "probable typo" in message
    assert "Closest indexed models by name:" in message
    assert "purchase.order" in message
    assert message.endswith(RETRY_INSTRUCTION)


def test_limit_and_determinism():
    G = _graph(*PURCHASE_GRAPH_MODELS)
    first = closest_models(G, "purchase.request", limit=2)
    assert len(first) == 2
    assert first == closest_models(G, "purchase.request", limit=2)
    assert closest_models(G, "purchase.request", limit=0) == []


def test_empty_graph_and_empty_name():
    assert closest_models(nx.DiGraph(), "purchase.request") == []
    assert closest_models(_graph(*PURCHASE_GRAPH_MODELS), "") == []


def test_non_model_nodes_are_never_suggested():
    G = _graph("purchase.order")
    G.add_node("model:purchase.fake", node_type="Field", name="purchase.fake")
    assert closest_models(G, "purchase.request") == ["purchase.order"]


def test_access_tool_exposes_suggestions_to_the_agent():
    G = _graph(*PURCHASE_GRAPH_MODELS)
    result = who_has_access_to(G, "purchase.request", "write")
    assert NOT_FOUND_MARKER in result.summary_text
    assert "purchase.order" in result.summary_text
