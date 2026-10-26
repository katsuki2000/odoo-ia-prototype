import networkx as nx

from code_intelligence.agent.technical_identifiers import replace_technical_identifiers


def _graph():
    graph = nx.DiGraph()
    graph.add_node("model:custom.purchase.request", node_type="Model", name="custom.purchase.request",
                   description="Demande d'achat interne",
                   window_actions=[{"xml_id": "ext_purchase_request.action_custom_purchase_request",
                                    "name": "Demandes d'achat"}])
    graph.add_node("model:purchase.order", node_type="Model", name="purchase.order",
                   description="Bon de commande fournisseur",
                   business_labels=[{"label": "Bon de commande fournisseur"}, {"label": "Purchase Order"}])
    graph.add_node("menu:purchase.menu_root", node_type="Menu", xml_id="purchase.menu_root", name="Purchase")
    return graph


def test_model_name_is_replaced_by_its_business_label():
    answer = "Le mod\u00e8le `custom.purchase.request` n'a pas de menu."
    assert replace_technical_identifiers(answer, _graph()) == "Le mod\u00e8le Demande d'achat interne n'a pas de menu."


def test_window_action_xml_id_is_replaced_by_the_action_name():
    answer = "L'action (XML ID : `ext_purchase_request.action_custom_purchase_request`) existe."
    assert replace_technical_identifiers(answer, _graph()) == "L'action (XML ID : Demandes d'achat) existe."


def test_menu_xml_id_is_replaced_by_the_menu_name():
    assert replace_technical_identifiers("Menu purchase.menu_root.", _graph()) == "Menu Purchase."


def test_every_label_of_the_node_is_shown_so_the_user_finds_the_interface_term():
    assert replace_technical_identifiers("purchase.order", _graph()) == "Bon de commande fournisseur / Purchase Order"


def test_unknown_identifiers_and_words_are_left_untouched():
    answer = "Voir odoo.com, etc. ou `ext_module.action_unknown`."
    assert replace_technical_identifiers(answer, _graph()) == answer


def test_a_longer_unknown_identifier_is_not_cut_at_a_known_prefix():
    answer = "Voir purchase.order.unknown_extension et purchase.order_extra."
    assert replace_technical_identifiers(answer, _graph()) == answer


def test_graph_without_identifier_leaves_the_answer_unchanged():
    assert replace_technical_identifiers("Bonjour.", nx.DiGraph()) == "Bonjour."
