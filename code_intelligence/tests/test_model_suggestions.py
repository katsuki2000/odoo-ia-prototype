import networkx as nx

from code_intelligence.rules.access_evaluator import who_has_access_to
from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.agent.tools import inspect_module_extensions, introspection, list_involved_modules
from code_intelligence.agent.tools.helpers import set_graph_ref
from code_intelligence.rules.model_suggestions import (
    RETRY_INSTRUCTION,
    closest_models,
    closest_modules,
    model_not_found_message,
    module_not_found_message,
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


def _module_graph():
    G = _graph("purchase.order", "stock.move")
    for name in ("purchase", "purchase_stock", "stock", "sale_stock"):
        G.add_node(f"module:{name}", node_type="Module", name=name)
    return G


def test_unknown_module_suggests_the_closest_indexed_modules():
    candidates = closest_modules(_module_graph(), "purchase_request")
    assert candidates[0] == "purchase"
    assert "stock" not in candidates


def test_models_are_never_suggested_as_modules_and_conversely():
    G = _module_graph()
    assert "purchase.order" not in closest_modules(G, "purchase.order")
    assert "purchase" not in closest_models(G, "purchase")


def test_module_message_keeps_marker_and_suggestions():
    message = module_not_found_message(_module_graph(), "purchase_request")
    assert NOT_FOUND_MARKER in message
    assert "module not installed" in message
    assert "Closest indexed modules by name: purchase" in message
    assert "exact module name" in message


def test_module_without_candidate_keeps_plain_message():
    message = module_not_found_message(_module_graph(), "inventory")
    assert NOT_FOUND_MARKER in message
    assert "Closest" not in message


def test_list_involved_modules_gives_candidates_for_an_absent_model():
    set_graph_ref(_graph(*PURCHASE_GRAPH_MODELS))
    result = list_involved_modules.invoke({"model_name": "purchase.request"})
    assert NOT_FOUND_MARKER in result
    assert "purchase.order" in result
    assert RETRY_INSTRUCTION in result


def test_list_involved_modules_still_describes_a_module_name(monkeypatch):
    monkeypatch.setattr(introspection, "_resolve_model_param", lambda name: name)
    G = _graph("alpha.beta", "gamma.delta")
    G.add_node("module:zeta_mod", node_type="Module", name="zeta_mod")
    G.add_edge("model:alpha.beta", "module:zeta_mod", edge_type="DEFINED_IN", role="declares")
    G.add_edge("model:gamma.delta", "module:zeta_mod", edge_type="DEFINED_IN", role="extends")
    set_graph_ref(G)
    result = list_involved_modules.invoke({"model_name": "zeta_mod"})
    assert "alpha.beta (declares), gamma.delta (extends)" in result
    assert NOT_FOUND_MARKER not in result


def test_inspect_module_extensions_does_not_state_a_false_fact_for_an_absent_module():
    set_graph_ref(_module_graph())
    result = inspect_module_extensions.invoke({"module_name": "inventory"})
    assert NOT_FOUND_MARKER in result
    assert "FAIT DÉTERMINISTE" not in result


def test_inspect_module_extensions_keeps_the_fact_for_an_installed_module_without_extension():
    set_graph_ref(_module_graph())
    result = inspect_module_extensions.invoke({"module_name": "stock"})
    assert "n'étend aucun modèle métier natif" in result
    assert NOT_FOUND_MARKER not in result
