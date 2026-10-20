import networkx as nx
import pytest

from code_intelligence.agent.matching import (
    _find_exact_technical_model_mentions,
    _find_exact_technical_module_mentions,
)


def _graph():
    graph = nx.DiGraph()
    for module in ("maintenance", "project", "hr_holidays", "point_of_sale", "base"):
        graph.add_node(f"module:{module}", node_type="Module", name=module)
    for model in ("base", "sale.order"):
        graph.add_node(f"model:{model}", node_type="Model", name=model)
    return graph


@pytest.mark.parametrize("question", [
    "que se passe-t-il quand une maintenance request est deplacee ?",
    "dans l'application maintenance, que fait le champ cost ?",
    "le project est-il visible pour un utilisateur ?",
    "ou trouver le point of sale dans le menu ?",
    "les conges de hr holidays sont-ils visibles ?",
])
def test_plain_word_is_not_a_module_mention(question):
    assert _find_exact_technical_module_mentions(question, _graph()) == []


@pytest.mark.parametrize("question, module", [
    ("dans le module maintenance, qui peut modifier une demande ?", "maintenance"),
    ("que fait l'addon project pour un utilisateur ?", "project"),
    ("le module hr_holidays gere les conges", "hr_holidays"),
    ("les regles de hr_holidays sont-elles actives ?", "hr_holidays"),
    ("le module point of sale est-il installe ?", "point_of_sale"),
    ("verifier point_of_sale pour ce groupe", "point_of_sale"),
])
def test_marked_or_technical_module_name_is_a_mention(question, module):
    assert module in _find_exact_technical_module_mentions(question, _graph())


def test_module_xmlid_prefix_is_still_ignored():
    assert _find_exact_technical_module_mentions("who can view project.group_project_user?", _graph()) == []


def test_plain_word_is_not_a_model_mention():
    question = "un utilisateur standard (groupe de base uniquement) peut-il voir ce menu ?"
    assert _find_exact_technical_model_mentions(question, _graph(), include_symbol_inference=False) == []


@pytest.mark.parametrize("question", ["que fait le modele base ?", "what does the model base do?"])
def test_marked_bare_model_name_is_a_mention(question):
    assert _find_exact_technical_model_mentions(question, _graph(), include_symbol_inference=False) == ["base"]


def test_dotted_model_name_and_xmlid_behaviour_are_unchanged():
    graph = _graph()
    assert _find_exact_technical_model_mentions("qui voit sale.order ?", graph, include_symbol_inference=False) == ["sale.order"]
    assert _find_exact_technical_model_mentions("who has base.group_portal?", graph, include_symbol_inference=False) == []
