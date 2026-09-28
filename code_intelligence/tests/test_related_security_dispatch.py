from code_intelligence.agent.forced_dispatch_predicates import security_locks_targets
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.graph.loader import get_code_intelligence_graph


def test_related_line_deletion_dispatches_order_and_line_models():
    question = (
        "Quelles regles empechent de supprimer une commande d'achat ou une de ses "
        "lignes selon leur etat ?"
    )
    graph = get_code_intelligence_graph()
    concept = resolve_business_term(question, graph, llm=None)

    assert concept.resolved_models == ["purchase.order"]
    assert security_locks_targets(concept, graph, question) == [
        "purchase.order",
        "purchase.order.line",
    ]


def test_default_dispatch_keeps_custom_security_scope_and_single_target():
    graph = get_code_intelligence_graph()
    concept = resolve_business_term("purchase order", graph, llm=None)
    assert security_locks_targets(concept, graph) == []
