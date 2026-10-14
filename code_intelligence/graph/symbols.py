"""Merge, rename, and resolve symbols from parsed Odoo modules."""

from code_intelligence.extractor.xml import (
    OdooActionRecord, OdooGroupRecord, OdooRuleRecord, OdooServerActionRecord,
)


def _merge_action(existing: OdooActionRecord, new: OdooActionRecord) -> OdooActionRecord:
    """Preserve fields omitted by an XML extension record."""
    new.res_model = new.res_model or existing.res_model
    new.view_mode = new.view_mode or existing.view_mode
    new.name = new.name or existing.name
    new.groups_id = new.groups_id or existing.groups_id
    return new


def _merge_server_action(existing: OdooServerActionRecord, new: OdooServerActionRecord) -> OdooServerActionRecord:
    new.model_id = getattr(new, "model_id", "") or getattr(existing, "model_id", "")
    new.name = getattr(new, "name", "") or getattr(existing, "name", "")
    return new


def _merge_rule(existing: OdooRuleRecord, new: OdooRuleRecord) -> OdooRuleRecord:
    new.model_id = getattr(new, "model_id", "") or getattr(existing, "model_id", "")
    new.domain_force = getattr(new, "domain_force", "") or getattr(existing, "domain_force", "")
    new.groups_id = getattr(new, "groups_id", None) or getattr(existing, "groups_id", [])
    return new


def _merge_group(existing: OdooGroupRecord, new: OdooGroupRecord) -> OdooGroupRecord:
    new.implied_ids = getattr(new, "implied_ids", None) or getattr(existing, "implied_ids", [])
    new.name = getattr(new, "name", "") or getattr(existing, "name", "")
    return new


from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import logging
import networkx as nx
from code_intelligence.extractor.python import OdooModelDeclaration

_logger = logging.getLogger(__name__)


@dataclass
class SymbolRename:
    old_symbol: str
    new_symbol: str
    symbol_type: str
    filepath: str
    class_name: Optional[str] = None
    old_name: str = ""
    new_name: str = ""


def detect_model_renames(G: nx.DiGraph, new_models: List[OdooModelDeclaration], filepath: str) -> List[SymbolRename]:
    """Detect renamed models whose source path and Python class are unchanged."""
    clean_fp = str(Path(filepath).resolve())
    renames = []
    existing_model_nodes = {}
    for node, attrs in G.nodes(data=True):
        if attrs.get("node_type") == "Model":
            fps = attrs.get("filepaths") or attrs.get("source_files") or []
            node_fp = attrs.get("filepath")
            if node_fp and str(Path(node_fp).resolve()) == clean_fp:
                existing_model_nodes[node] = attrs
            elif any(str(Path(f).resolve()) == clean_fp for f in fps):
                existing_model_nodes[node] = attrs
    if not existing_model_nodes:
        return renames
    class_to_old_node = {}
    for node_id, attrs in existing_model_nodes.items():
        c_name = attrs.get("class_name")
        if c_name:
            class_to_old_node[c_name] = node_id
    for m in new_models:
        if m.name and m.class_name in class_to_old_node:
            old_node_id = class_to_old_node[m.class_name]
            old_model_name = G.nodes[old_node_id].get("name") or old_node_id.replace("model:", "")
            new_model_name = m.name
            if old_model_name != new_model_name:
                renames.append(SymbolRename(
                    old_symbol=old_node_id,
                    new_symbol=f"model:{new_model_name}",
                    symbol_type="model",
                    filepath=filepath,
                    class_name=m.class_name,
                    old_name=old_model_name,
                    new_name=new_model_name,
                ))
    return renames


def refactor_rename_in_graph(G: nx.DiGraph, renames: List[SymbolRename]) -> Tuple[nx.DiGraph, Dict[str, Any]]:
    """Rewire renamed graph nodes while preserving their attributes."""
    if not renames:
        return G, {"renamed_count": 0, "rewired_edges_count": 0, "details": []}
    H = G.copy()
    rewired_edges_count = 0
    details = []
    for r in renames:
        old_id, new_id = r.old_symbol, r.new_symbol
        if not H.has_node(old_id):
            _logger.warning("Rename target node %s not found in graph", old_id)
            continue
        attrs = dict(H.nodes[old_id])
        attrs["name"] = r.new_name or attrs.get("name")
        attrs["previous_names"] = attrs.get("previous_names", []) + [r.old_name]
        H.add_node(new_id, **attrs)
        for pred in list(H.predecessors(old_id)):
            H.add_edge(pred, new_id, **dict(H.get_edge_data(pred, old_id)))
            rewired_edges_count += 1
        for succ in list(H.successors(old_id)):
            H.add_edge(new_id, succ, **dict(H.get_edge_data(old_id, succ)))
            rewired_edges_count += 1
        H.remove_node(old_id)
        details.append({"old_symbol": old_id, "new_symbol": new_id, "class_name": r.class_name, "filepath": r.filepath})
        _logger.info("Refactored graph node %s -> %s (class=%s)", old_id, new_id, r.class_name)
    return H, {"renamed_count": len(details), "rewired_edges_count": rewired_edges_count, "details": details}


from code_intelligence.utils import qualify_xml_id
from .integrity import _detect_inheritance_cycles, topological_sort_modules
from .nodes import CORE_BASE_MODULES, ParsedModule, ResolvedSymbolRegistry, UnresolvedCategory, UnresolvedReference, _categorize_unresolved


def build_module_symbol_registry(modules_dict: Dict[str, ParsedModule]) -> ResolvedSymbolRegistry:
    """Index definitions before resolving cross-module references."""
    registry = ResolvedSymbolRegistry()
    load_order = topological_sort_modules(modules_dict)
    for mod_name in load_order:
        mod = modules_dict.get(mod_name)
        if not mod:
            continue
        for decl in mod.models:
            model_key = decl.name
            if not model_key and decl.inherit:
                model_key = decl.inherit[0]
            if model_key:
                registry.models.setdefault(model_key, []).append(decl)
                registry.model_modules.setdefault(model_key, []).append(mod_name)
        for grp in mod.groups:
            full_xml_id = qualify_xml_id(grp.xml_id, mod_name)
            existing = registry.groups.get(full_xml_id)
            if existing:
                grp = _merge_group(existing, grp)
            registry.groups[full_xml_id] = grp
            registry.groups[grp.xml_id] = grp
        for rule in mod.rules:
            full_xml_id = qualify_xml_id(rule.xml_id, mod_name)
            existing = registry.rules.get(full_xml_id)
            if existing:
                rule = _merge_rule(existing, rule)
            registry.rules[full_xml_id] = rule
            registry.rules[rule.xml_id] = rule
        for act in mod.actions:
            full_xml_id = qualify_xml_id(act.xml_id, mod_name)
            existing = registry.actions.get(full_xml_id)
            if existing:
                act = _merge_action(existing, act)
            registry.actions[full_xml_id] = act
            registry.actions[act.xml_id] = act
        for sa in mod.server_actions:
            full_xml_id = qualify_xml_id(sa.xml_id, mod_name)
            existing = registry.server_actions.get(full_xml_id)
            if existing:
                sa = _merge_server_action(existing, sa)
            registry.server_actions[full_xml_id] = sa
            registry.server_actions[sa.xml_id] = sa
        for ba in mod.base_automations:
            full_xml_id = qualify_xml_id(ba.xml_id, mod_name)
            registry.base_automations[full_xml_id] = ba
            registry.base_automations[ba.xml_id] = ba
        for menu in mod.menuitems:
            full_xml_id = qualify_xml_id(menu.xml_id, mod_name)
            registry.menuitems[full_xml_id] = menu
            registry.menuitems[menu.xml_id] = menu
        for view in mod.views:
            full_xml_id = qualify_xml_id(view.xml_id, mod_name)
            registry.views[full_xml_id] = view
            registry.views[view.xml_id] = view
    for mod_name in load_order:
        mod = modules_dict.get(mod_name)
        if not mod:
            continue
        for decl in mod.models:
            for parent_ref in decl.inherit:
                _resolve_model_reference(mod_name, decl.filepath, parent_ref, registry)
            for parent_ref, fk_field in decl.inherits.items():
                _resolve_model_reference(mod_name, decl.filepath, parent_ref, registry)
        for rule in mod.rules:
            if rule.model_id:
                _resolve_model_reference(mod_name, rule.filepath, rule.model_id, registry)
            for grp_ref in rule.groups_id:
                _resolve_group_reference(mod_name, rule.filepath, grp_ref, registry)
        for grp in mod.groups:
            for parent_grp_ref in grp.implied_ids:
                _resolve_group_reference(mod_name, grp.filepath, parent_grp_ref, registry)
    _detect_inheritance_cycles(registry)
    return registry


def _resolve_model_reference(mod_name: str, filepath: str, model_ref: str, registry: ResolvedSymbolRegistry):
    registry.resolve_model_ref_or_record(model_ref, mod_name, filepath)


def _resolve_group_reference(mod_name: str, filepath: str, group_ref: str, registry: ResolvedSymbolRegistry):
    if group_ref in registry.groups or qualify_xml_id(group_ref, mod_name) in registry.groups:
        return
    registry.unresolved_references.append(UnresolvedReference(
        source_module=mod_name, source_file=filepath, symbol_ref=group_ref, ref_type="group",
        category=_categorize_unresolved(mod_name, group_ref),
        detail=f"Group '{group_ref}' referenced in {mod_name} not found in index.",
    ))


__all__ = [
    "_merge_action", "_merge_server_action", "_merge_rule", "_merge_group", "SymbolRename",
    "detect_model_renames", "refactor_rename_in_graph", "build_module_symbol_registry",
    "_resolve_model_reference", "_resolve_group_reference", "_categorize_unresolved",
]
