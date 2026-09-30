from pathlib import Path

import networkx as nx

from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.graph.instance_fingerprint import build_instance_fingerprint
from code_intelligence.graph.translations import (
    attach_translations,
    parse_po,
)


def test_po_translations_link_models_fields_menus_and_selections(tmp_path: Path):
    po_path = tmp_path / "fr.po"
    po_path.write_text(
        '#: model:ir.model,name:purchase.model_purchase_order\n'
        'msgid "Purchase Order"\n'
        'msgstr "Bon de commande fournisseur"\n\n'
        '#: model:ir.model.fields,field_description:purchase.field_purchase_order__state\n'
        'msgid "Status"\n'
        'msgstr "État"\n\n'
        '#: model:ir.model.fields.selection,name:purchase.selection__purchase_order__state__purchase\n'
        'msgid "Purchase"\n'
        'msgstr "Achat confirmé"\n\n'
        '#: model:ir.ui.menu,name:purchase.menu_purchase_root\n'
        'msgid "Purchase"\n'
        'msgstr "Achats"\n',
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node("model:purchase.order", node_type="Model", name="purchase.order")
    graph.add_node(
        "field:purchase.order.state",
        node_type="Field",
        model="purchase.order",
        name="state",
    )
    graph.add_node("menu:purchase.menu_purchase_root", node_type="Menu", name="Purchase")
    entries = parse_po(po_path, "purchase")

    summary = attach_translations(graph, entries)

    assert summary == {"attached": 4, "unlinked": 0}
    assert graph.nodes["model:purchase.order"]["business_labels"][0]["label"] == "Bon de commande fournisseur"
    assert graph.nodes["field:purchase.order.state"]["business_labels"][1]["entity_type"] == "selection"
    assert graph.nodes["menu:purchase.menu_purchase_root"]["business_labels"][0]["source"] == "po"


def test_resolver_can_disable_static_aliases_and_use_instance_labels():
    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        name="purchase.order",
        description="Purchase Order",
        business_labels=[{
            "label": "Bon de commande fournisseur",
            "language": "fr",
            "source": "po",
        }],
    )
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        name="sale.order",
        description="Sales Order",
        business_labels=[{
            "label": "Commande client",
            "language": "fr",
            "source": "po",
        }],
    )

    result = resolve_business_term(
        "bon de commande fournisseur",
        graph,
        llm=None,
        language="fr_FR",
        use_static_aliases=False,
    )

    assert result.resolved_models == ["purchase.order"]
    assert result.source_step == "fuzzy_graph_match"


def test_generic_command_does_not_default_to_sales_or_purchase():
    graph = nx.DiGraph()
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        name="purchase.order",
        description="Purchase Order",
        business_labels=[{"label": "Bon de commande fournisseur", "language": "fr"}],
    )
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        name="sale.order",
        description="Sales Order",
        business_labels=[{"label": "Commande client", "language": "fr"}],
    )

    result = resolve_business_term(
        "commande",
        graph,
        llm=None,
        language="fr",
        use_static_aliases=False,
    )

    assert not result.is_resolved
    assert result.resolved_models == []


def test_instance_fingerprint_marks_missing_runtime_inventory():
    fingerprint = build_instance_fingerprint(
        installed_modules=None,
        addon_paths=[],
        active_languages=None,
        request_language="fr",
        source_modules={"purchase": "17.0"},
    )

    assert fingerprint.runtime_inventory_available is False
    assert fingerprint.language_inventory_available is False
    assert fingerprint.source_modules == (("purchase", "17.0"),)
    assert fingerprint.digest
