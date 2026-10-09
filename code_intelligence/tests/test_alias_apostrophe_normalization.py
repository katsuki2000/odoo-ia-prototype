import networkx as nx
import pytest

from code_intelligence.agent.aliases import normalize_alias_text
from code_intelligence.agent.resolver import resolve_business_term


@pytest.fixture
def graph():
    graph = nx.DiGraph()
    for model in ("purchase.order", "sale.order"):
        graph.add_node(f"model:{model}", node_type="Model", name=model)
    return graph


@pytest.mark.parametrize("apostrophe", ["'", "\u2019", "\u2018", "\u02bc"])
def test_apostrophe_variants_resolve_the_same_alias(graph, apostrophe):
    question = f"comment confirmer une commande d{apostrophe}achat ?"
    concept = resolve_business_term(question, graph, llm=None)
    assert concept.is_resolved is True
    assert concept.resolved_models == ["purchase.order"]
    assert concept.source_step == "static_alias"


def test_shorter_alias_still_applies_without_the_longer_phrase(graph):
    concept = resolve_business_term("comment confirmer une commande ?", graph, llm=None)
    assert concept.resolved_models == ["sale.order"]


def test_normalization_keeps_accents_composed():
    decomposed = "e\u0301criture d\u2019achat"
    assert normalize_alias_text(decomposed) == "\u00e9criture d'achat"
