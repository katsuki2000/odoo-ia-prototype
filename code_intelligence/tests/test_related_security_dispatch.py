from code_intelligence.agent.forced_dispatch_predicates import (
    data_constraints_targets,
    security_locks_targets,
)
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.graph.loader import get_code_intelligence_graph


def test_related_line_deletion_dispatches_order_and_line_models():
    question = (
        "Quelles regles empechent de supprimer une commande d'achat ou une de ses "
        "lignes selon leur etat ?"
    )
    graph = get_code_intelligence_graph()
    concept = resolve_business_term(question, graph, llm=None, use_static_aliases=True)

    assert concept.resolved_models == ["purchase.order"]
    assert security_locks_targets(concept, graph, question) == [
        "purchase.order",
        "purchase.order.line",
    ]


def test_related_line_constraint_dispatches_order_and_line_models():
    question = (
        "Quelles regles empechent de supprimer une commande d'achat ou une de ses "
        "lignes selon leur etat, et quelle contrainte SQL distincte s'applique "
        "sur les lignes elles-memes ?"
    )
    graph = get_code_intelligence_graph()
    concept = resolve_business_term(question, graph, llm=None, use_static_aliases=True)

    assert data_constraints_targets(concept, graph, question) == [
        "purchase.order",
        "purchase.order.line",
    ]


def test_constraint_dispatch_keeps_single_target_without_related_line_question():
    graph = get_code_intelligence_graph()
    concept = resolve_business_term("purchase.order", graph, llm=None, use_static_aliases=True)

    assert data_constraints_targets(concept, graph, "Quelles contraintes SQL s'appliquent ?") == [
        "purchase.order",
    ]


def test_default_security_dispatch_does_not_expand_beyond_resolved_scope():
    graph = get_code_intelligence_graph()
    concept = resolve_business_term("purchase order", graph, llm=None, use_static_aliases=True)

    targets = security_locks_targets(concept, graph)
    assert len(targets) <= 1
    assert set(targets).issubset(set(concept.resolved_models))
