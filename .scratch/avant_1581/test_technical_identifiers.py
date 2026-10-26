import networkx as nx

from code_intelligence.agent.technical_identifiers import replace_model_identifiers


def _graph():
    graph = nx.DiGraph()
    graph.add_node("model:custom.purchase.request", node_type="Model", name="custom.purchase.request",
                   description="Demande d'achat interne")
    graph.add_node("model:res.partner", node_type="Model", name="res.partner", description="Contact")
    return graph


def test_model_name_is_replaced_by_its_business_label():
    answer = "Le mod\u00e8le `custom.purchase.request` n'a pas de menu."
    assert replace_model_identifiers(answer, _graph()) == "Le mod\u00e8le Demande d'achat interne n'a pas de menu."


def test_every_occurrence_is_replaced_with_or_without_backticks():
    answer = "res.partner puis `res.partner` et custom.purchase.request."
    assert replace_model_identifiers(answer, _graph()) == "Contact puis Contact et Demande d'achat interne."


def test_dotted_words_that_are_not_graph_models_are_left_untouched():
    answer = "Voir odoo.com, une demande, etc. ou `ext_module.action_unknown`."
    assert replace_model_identifiers(answer, _graph()) == answer


def test_text_without_identifier_is_unchanged():
    answer = "Ouvrez le menu Achats puis cr\u00e9ez une demande."
    assert replace_model_identifiers(answer, _graph()) == answer
