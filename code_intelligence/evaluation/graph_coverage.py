"""Coverage diagnostics for a serialized Code Intelligence graph."""

from __future__ import annotations

from typing import Any, Optional


def _matches_language(label: dict[str, Any], language: Optional[str]) -> bool:
    if not language:
        return bool(label.get("label"))
    label_language = str(label.get("language") or "").lower()
    requested = language.lower()
    return bool(label.get("label")) and (
        label_language == requested
        or label_language.split("_", 1)[0] == requested.split("_", 1)[0]
    )


def _coverage(total: int, covered: int) -> dict[str, int | float | None]:
    return {
        "total": total,
        "covered": covered,
        "ratio": covered / total if total else None,
    }


def build_graph_coverage_report(graph, *, language: Optional[str] = None) -> dict[str, Any]:
    """Summarize graph labels and unresolved menu actions for one language."""
    nodes_by_type = {
        node_type: [
            (node_id, data)
            for node_id, data in graph.nodes(data=True)
            if data.get("node_type") == node_type
        ]
        for node_type in ("Model", "Field", "Menu")
    }
    models = nodes_by_type["Model"]
    fields = nodes_by_type["Field"]
    menus = nodes_by_type["Menu"]
    menus_with_action = [
        (node_id, data)
        for node_id, data in menus
        if data.get("action_ref")
    ]
    menus_with_model = {
        node_id
        for node_id, _data in menus_with_action
        if any(
            graph.edges[node_id, target].get("edge_type") == "OPENS_MODEL"
            for target in graph.successors(node_id)
        )
    }
    unresolved_menus = [
        (node_id, data)
        for node_id, data in menus_with_action
        if node_id not in menus_with_model
    ]
    fingerprint_data = graph.graph.get("instance_fingerprint_data") or {}
    indexed_modules = {
        data.get("name", node_id.removeprefix("module:"))
        for node_id, data in graph.nodes(data=True)
        if data.get("node_type") == "Module"
    }
    runtime_modules = {
        row[0]
        for row in fingerprint_data.get("modules", [])
        if row and row[0]
    }
    runtime_inventory_available = bool(fingerprint_data.get("runtime_inventory_available"))
    runtime_translation_summary = graph.graph.get("runtime_translation_summary") or {}

    def translated(nodes: list[tuple[str, dict[str, Any]]]) -> int:
        return sum(
            any(_matches_language(label, language) for label in data.get("business_labels", []))
            for _node_id, data in nodes
        )

    return {
        "instance_fingerprint": graph.graph.get("instance_fingerprint"),
        "instance_fingerprint_data": fingerprint_data,
        "language": language,
        "coverage": {
            "model_descriptions": _coverage(
                len(models), sum(bool(data.get("description")) for _node_id, data in models),
            ),
            "field_labels": _coverage(
                len(fields), sum(bool(data.get("label")) for _node_id, data in fields),
            ),
            "menu_actions_opening_models": _coverage(
                len(menus_with_action), len(menus_with_model),
            ),
            "folder_menus": _coverage(len(menus), len(menus) - len(menus_with_action)),
            "model_business_labels": _coverage(len(models), translated(models)),
            "field_business_labels": _coverage(len(fields), translated(fields)),
            "menu_business_labels": _coverage(len(menus), translated(menus)),
        },
        "unresolved_menu_actions": [
            {
                "node_id": node_id,
                "name": data.get("name"),
                "action_ref": data.get("action_ref"),
            }
            for node_id, data in unresolved_menus
        ],
        "runtime_inventory": {
            "available": runtime_inventory_available,
            "installed_module_count": len(runtime_modules) if runtime_inventory_available else None,
            "unindexed_installed_modules": sorted(runtime_modules - indexed_modules)
            if runtime_inventory_available else [],
        },
        "runtime_translations": {
            "active_languages_available": runtime_translation_summary.get(
                "active_languages_available",
            ),
            "queried_languages": runtime_translation_summary.get("queried_languages", []),
            "model_records": runtime_translation_summary.get("model_records", 0),
            "field_records": runtime_translation_summary.get("field_records", 0),
            "attached": runtime_translation_summary.get("attached", 0),
            "unlinked": runtime_translation_summary.get("unlinked", 0),
            "failed_languages": runtime_translation_summary.get("failed_languages", []),
        },
        "unresolved_references": graph.graph.get("unresolved_references", []),
    }


__all__ = ["build_graph_coverage_report"]
