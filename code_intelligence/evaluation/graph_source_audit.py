"""Audit of what the graph keeps from the module sources: node coverage, attribute-only kinds, kinds never extracted."""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import networkx as nx

from .source_inventory import ACCESS_KIND, ModuleInventory, inventory_module

EXAMPLE_LIMIT = 10

NODE_KINDS: Dict[str, Tuple[str, ...]] = {
    "Group": ("res.groups",),
    "Rule": ("ir.rule",),
    "Menu": ("ir.ui.menu",),
    "ServerAction": ("ir.actions.server", "ir.cron"),
    "AutomationRule": ("base.automation",),
    "AccessEntry": (ACCESS_KIND,),
    "Category": ("ir.module.category",),
    "Report": ("ir.actions.report",),
    "MailTemplate": ("mail.template",),
    "HttpRoute": ("http_route",),
}
ATTRIBUTE_ONLY_KINDS: Dict[str, str] = {
    "ir.ui.view": "buttons only",
    "ir.actions.act_window": "Model.window_actions and Menu attributes",
    "ir.actions.client": "Menu attributes",
    "js_client_action_tag": "Menu -> Model edge",
}


def _graph_xml_id(nodeId: str, data: Dict[str, Any]) -> str:
    return data.get("xml_id") or nodeId.partition(":")[2]


def _graph_ids(G: nx.DiGraph) -> Dict[str, Set[str]]:
    ids: Dict[str, Set[str]] = {nodeType: set() for nodeType in NODE_KINDS}
    for nodeId, data in G.nodes(data=True):
        if data.get("node_type") in ids:
            ids[data["node_type"]].add(_graph_xml_id(nodeId, data))
    return ids


def _module_directories(G: nx.DiGraph) -> Dict[str, Path]:
    return {
        data.get("name") or nodeId.removeprefix("module:"): Path(data["filepath"]).parent
        for nodeId, data in G.nodes(data=True)
        if data.get("node_type") == "Module" and data.get("filepath")
    }


def _node_row(nodeType: str, diskIds: Set[str], graphIds: Set[str], modules: Set[str]) -> Dict[str, Any]:
    missing = sorted(diskIds - graphIds)
    extra = sorted(identifier for identifier in graphIds - diskIds if identifier.split(".", 1)[0] in modules)
    return {
        "kind": nodeType,
        "status": "covered" if not missing else "partial",
        "disk": len(diskIds),
        "graph": len(graphIds),
        "missing": len(missing),
        "extra": len(extra),
        "missing_examples": missing[:EXAMPLE_LIMIT],
    }


def build_source_audit(G: nx.DiGraph) -> Dict[str, Any]:
    directories = _module_directories(G)
    available = {name: path for name, path in directories.items() if path.is_dir()}
    diskIds: Dict[str, Set[str]] = {}
    diskCounts: Counter = Counter()
    for moduleDir in available.values():
        inventory: ModuleInventory = inventory_module(moduleDir)
        diskCounts.update(inventory.counts)
        for kind, ids in inventory.xmlIds.items():
            diskIds.setdefault(kind, set()).update(ids)
    graphIds = _graph_ids(G)
    modules = set(available)
    rows: List[Dict[str, Any]] = [
        _node_row(nodeType, set().union(*(diskIds.get(kind, set()) for kind in kinds)), graphIds[nodeType], modules)
        for nodeType, kinds in NODE_KINDS.items()
    ]
    handled = {kind for kinds in NODE_KINDS.values() for kind in kinds}
    rows.extend(
        {"kind": kind, "status": "attribute_only", "disk": diskCounts[kind], "kept_as": keptAs}
        for kind, keptAs in ATTRIBUTE_ONLY_KINDS.items()
    )
    handled |= set(ATTRIBUTE_ONLY_KINDS)
    rows.extend(
        {"kind": kind, "status": "not_extracted", "disk": count}
        for kind, count in diskCounts.most_common() if kind not in handled
    )
    return {
        "modules_audited": len(available),
        "modules_without_source": sorted(set(directories) - modules),
        "kinds": rows,
    }
