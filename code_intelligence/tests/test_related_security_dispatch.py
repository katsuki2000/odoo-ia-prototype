from code_intelligence.agent.forced_dispatch_predicates import (
    data_constraints_targets,
    security_locks_targets,
)
from code_intelligence.agent.matching import ResolvedConcept
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.graph.loader import get_code_intelligence_graph


def _resolved_purchase_order(question: str) -> ResolvedConcept:
    """Concept already resolved to `purchase.order`: the subject of these tests is
    the dispatch expansion to line models, not the resolution of the business term
    (static aliases were removed, section 1436)."""
    return ResolvedConcept(
        user_term=question, resolved_models=["purchase.order"], confidence=1.0,
        source_step="exact_technical_mention", is_resolved=True, reason="synthetic",
    )


def test_related_line_deletion_dispatches_order_and_line_models():
    question = (
        "Quelles regles empechent de supprimer une commande d'achat ou une de ses "
        "lignes selon leur etat ?"
    )
    graph = get_code_intelligence_graph()
    concept = _resolved_purchase_order(question)

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
    concept = _resolved_purchase_order(question)

    assert data_constraints_targets(concept, graph, question) == [
        "purchase.order",
        "purchase.order.line",
    ]


def test_constraint_dispatch_keeps_single_target_without_related_line_question():
    graph = get_code_intelligence_graph()
    concept = resolve_business_term("purchase.order", graph, llm=None)

    assert data_constraints_targets(concept, graph, "Quelles contraintes SQL s'appliquent ?") == [
        "purchase.order",
    ]


def test_default_security_dispatch_does_not_expand_beyond_resolved_scope():
    graph = get_code_intelligence_graph()
    concept = resolve_business_term("purchase order", graph, llm=None)

    targets = security_locks_targets(concept, graph)
    assert len(targets) <= 1
    assert set(targets).issubset(set(concept.resolved_models))
