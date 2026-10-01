from pathlib import Path

import networkx as nx

from code_intelligence.agent.matching import _build_fuzzy_index, _fuzzy_match_graph
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.graph.instance_fingerprint import build_instance_fingerprint
from code_intelligence.graph.loader import _translation_cache_matches
from code_intelligence.graph.translations import (
    attach_translations,
    load_module_translations,
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

    no_language = resolve_business_term(
        "bon de commande fournisseur",
        graph,
        llm=None,
        use_static_aliases=False,
    )
    assert not no_language.is_resolved


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


def test_fuzzy_matching_normalizes_contractions_for_instance_labels():
    graph = nx.DiGraph()
    graph.add_node("module:purchase", node_type="Module")
    graph.add_node(
        "model:purchase.order",
        node_type="Model",
        name="purchase.order",
        description="Purchase Order",
        business_labels=[{"label": "Commande d'achat", "language": "fr"}],
    )
    graph.add_edge(
        "model:purchase.order", "module:purchase", edge_type="DEFINED_IN", role="declares",
    )
    graph.add_node(
        "menu:purchase.root",
        node_type="Menu",
        name="Purchase",
        module="purchase",
        business_labels=[{"label": "Achats", "language": "fr"}],
    )

    matches = _fuzzy_match_graph("commande d'achat", graph, language="fr", use_static_synonyms=False)

    assert matches[0][0] == "purchase.order"


def test_exact_field_and_model_label_pair_outweighs_generic_access_phrase():
    graph = nx.DiGraph()
    graph.add_node(
        "model:maintenance.equipment",
        node_type="Model",
        name="maintenance.equipment",
        description="Maintenance Equipment",
        business_labels=[{"label": "Equipement de maintenance", "language": "fr"}],
    )
    graph.add_node(
        "field:maintenance.equipment.cost",
        node_type="Field",
        model="maintenance.equipment",
        name="cost",
        label="Cost",
    )
    graph.add_node(
        "model:ir.model.access",
        node_type="Model",
        name="ir.model.access",
        description="Model Access",
        business_labels=[{"label": "Acces en lecture", "language": "fr"}],
    )

    result = resolve_business_term(
        "Pourquoi le champ 'cost' d'un equipement n'est-il pas visible pour tous "
        "les utilisateurs ayant acces en lecture a sa fiche ?",
        graph,
        llm=None,
        language="fr",
        use_static_aliases=False,
    )

    assert result.resolved_models == ["maintenance.equipment"]
    assert result.source_step == "fuzzy_graph_match"


def test_root_menu_labels_attach_only_to_models_declared_by_the_module():
    graph = nx.DiGraph()
    graph.add_node("module:base", node_type="Module")
    graph.add_node("module:stock", node_type="Module")
    graph.add_node(
        "model:res.partner",
        node_type="Model",
        name="res.partner",
        description="Contact",
    )
    graph.add_node(
        "model:stock.picking",
        node_type="Model",
        name="stock.picking",
        description="Transfer",
    )
    graph.add_edge(
        "model:res.partner", "module:base", edge_type="DEFINED_IN", role="declares",
    )
    graph.add_edge(
        "model:res.partner", "module:stock", edge_type="DEFINED_IN", role="extends",
    )
    graph.add_edge(
        "model:stock.picking", "module:stock", edge_type="DEFINED_IN", role="declares",
    )
    graph.add_node(
        "menu:stock.root",
        node_type="Menu",
        name="Inventory",
        module="stock",
        business_labels=[{"label": "Inventaire", "language": "fr"}],
    )

    index = _build_fuzzy_index(graph, "fr", use_static_synonyms=False)

    assert ("contact inventaire", "res.partner") not in index
    assert ("transfer inventaire", "stock.picking") in index


def test_module_resolution_returns_declared_models_not_extensions():
    graph = nx.DiGraph()
    graph.add_node("module:stock", node_type="Module", name="stock")
    graph.add_node("model:res.partner", node_type="Model", name="res.partner")
    graph.add_node("model:stock.picking", node_type="Model", name="stock.picking")
    graph.add_edge(
        "model:res.partner", "module:stock", edge_type="DEFINED_IN", role="extends",
    )
    graph.add_edge(
        "model:stock.picking", "module:stock", edge_type="DEFINED_IN", role="declares",
    )

    result = resolve_business_term("module stock", graph, use_static_aliases=False)

    assert result.resolved_models == ["stock.picking"]


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


def test_translation_cache_reuses_superset_catalogs_but_requires_requested_languages():
    assert _translation_cache_matches((), ("fr",))
    assert _translation_cache_matches(("fr",), ("fr", "en"))
    assert not _translation_cache_matches(("en",), ("fr",))
    assert _translation_cache_matches((), ())


def test_regional_catalog_precedes_base_catalog_and_base_is_fallback(tmp_path: Path):
    module_dir = tmp_path / "module"
    i18n_dir = module_dir / "i18n"
    i18n_dir.mkdir(parents=True)
    (i18n_dir / "fr.po").write_text(
        'msgid "Order"\nmsgstr "Commande"\n', encoding="utf-8",
    )
    (i18n_dir / "fr_CA.po").write_text(
        'msgid "Order"\nmsgstr "Commande régionale"\n', encoding="utf-8",
    )

    regional = load_module_translations(module_dir, "module", ["fr_CA"])
    fallback = load_module_translations(module_dir, "module", ["fr_BE"])

    assert [entry.msgstr for entry in regional] == ["Commande régionale"]
    assert [entry.msgstr for entry in fallback] == ["Commande"]
