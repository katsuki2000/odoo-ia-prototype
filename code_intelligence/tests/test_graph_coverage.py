import networkx as nx

from code_intelligence.evaluation.graph_coverage import build_graph_coverage_report
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.graph.nodes import (
    ResolvedSymbolRegistry,
    UnresolvedCategory,
    UnresolvedReference,
)


def test_graph_coverage_reports_labels_and_unresolved_menu_actions():
    graph = nx.DiGraph()
    graph.graph["instance_fingerprint"] = "instance-a"
    graph.add_node(
        "model:sale.order",
        node_type="Model",
        description="Sales Order",
        business_labels=[{"label": "Commande client", "language": "fr"}],
    )
    graph.add_node(
        "field:sale.order.state",
        node_type="Field",
        label="Status",
        business_labels=[{"label": "Statut", "language": "fr_FR"}],
    )
    graph.add_node(
        "menu:sale.orders",
        node_type="Menu",
        name="Orders",
        action_ref="sale.action_orders",
    )
    graph.add_node(
        "menu:sale.broken",
        node_type="Menu",
        name="Broken",
        action_ref="sale.action_missing",
    )
    graph.add_node("menu:sale.root", node_type="Menu", name="Sales")
    graph.add_edge("menu:sale.orders", "model:sale.order", edge_type="OPENS_MODEL")

    report = build_graph_coverage_report(graph, language="fr")

    assert report["instance_fingerprint"] == "instance-a"
    assert report["coverage"]["model_business_labels"] == {
        "total": 1,
        "covered": 1,
        "ratio": 1.0,
    }
    assert report["coverage"]["field_business_labels"]["covered"] == 1
    assert report["coverage"]["menu_actions_opening_models"] == {
        "total": 2,
        "covered": 1,
        "ratio": 0.5,
    }
    assert report["coverage"]["folder_menus"]["covered"] == 1
    assert report["unresolved_menu_actions"] == [{
        "node_id": "menu:sale.broken",
        "name": "Broken",
        "action_ref": "sale.action_missing",
    }]
    assert report["runtime_inventory"]["available"] is False


def test_graph_coverage_uses_base_language_for_regional_labels():
    graph = nx.DiGraph()
    graph.add_node(
        "model:stock.picking",
        node_type="Model",
        business_labels=[{"label": "Transfert", "language": "fr_CA"}],
    )

    report = build_graph_coverage_report(graph, language="fr_BE")

    assert report["coverage"]["model_business_labels"]["covered"] == 1


def test_graph_coverage_exposes_runtime_modules_and_unresolved_references():
    registry = ResolvedSymbolRegistry(unresolved_references=[
        UnresolvedReference(
            source_module="custom_sales",
            source_file="views/sale.xml",
            symbol_ref="custom_sales.action_missing",
            ref_type="action",
            category=UnresolvedCategory.ABSENT_FROM_CORPUS,
        ),
    ])
    graph = OdooGraphBuilder(registry, {}).build_graph()
    graph.graph["instance_fingerprint_data"] = {
        "runtime_inventory_available": True,
        "modules": [("base", "17.0", "installed"), ("custom_sales", "17.0", "installed")],
    }
    graph.add_node("module:base", node_type="Module", name="base")

    report = build_graph_coverage_report(graph)

    assert report["runtime_inventory"] == {
        "available": True,
        "installed_module_count": 2,
        "unindexed_installed_modules": ["custom_sales"],
    }
    assert report["unresolved_references"] == [{
        "source_module": "custom_sales",
        "source_file": "views/sale.xml",
        "symbol_ref": "custom_sales.action_missing",
        "ref_type": "action",
        "category": "absent_from_corpus",
        "detail": "",
    }]


def test_graph_coverage_exposes_runtime_translation_attachment_gaps():
    graph = nx.DiGraph()
    graph.graph["runtime_translation_summary"] = {
        "active_languages_available": True,
        "queried_languages": ["fr_FR"],
        "model_records": 3,
        "field_records": 8,
        "attached": 7,
        "unlinked": 4,
        "failed_languages": [],
    }

    report = build_graph_coverage_report(graph)

    assert report["runtime_translations"] == {
        "active_languages_available": True,
        "queried_languages": ["fr_FR"],
        "model_records": 3,
        "field_records": 8,
        "attached": 7,
        "unlinked": 4,
        "failed_languages": [],
    }
