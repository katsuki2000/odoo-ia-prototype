"""
code_intelligence/graph/symbol_merger.py

Merge helpers for XML records extended across modules in Odoo load order.
"""

from code_intelligence.extractor.xml import (
    OdooActionRecord,
    OdooGroupRecord,
    OdooRuleRecord,
    OdooServerActionRecord,
)


def _merge_action(existing: OdooActionRecord, new: OdooActionRecord) -> OdooActionRecord:
    """
    Merge an extension record (e.g. <record id="base.action_partner_form">
    re-declared in a dependent module to tweak view_mode/domain/context)
    onto the originally-declared action, instead of overwriting it wholesale.
    Odoo's own record-inheritance semantics only replace the fields the
    extension explicitly sets; fields it omits keep their inherited value.
    """
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


__all__ = [
    "_merge_action",
    "_merge_server_action",
    "_merge_rule",
    "_merge_group",
]

# ── Symbol Refactoring ───────────────────────────────────────────────────

"""
code_intelligence/graph_symbol_refactor.py

Incremental Symbol & Model Rename Handler:
Detects and processes symbol/model renames across the Odoo Code Intelligence knowledge graph.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
import logging
import networkx as nx

from code_intelligence.extractor.python import OdooModelDeclaration

_logger = logging.getLogger(__name__)


@dataclass
class SymbolRename:
    """Represents a detected symbol or model rename."""
    old_symbol: str        # e.g. "model:custom.asset.loan"
    new_symbol: str        # e.g. "model:custom.asset.lending"
    symbol_type: str       # "model", "field", "group", "xml_id"
    filepath: str
    class_name: Optional[str] = None
    old_name: str = ""     # e.g. "custom.asset.loan"
    new_name: str = ""     # e.g. "custom.asset.lending"


def detect_model_renames(
    G: nx.DiGraph,
    new_models: List[OdooModelDeclaration],
    filepath: str,
) -> List[SymbolRename]:
    """
    Compare existing models in graph G associated with filepath
    against newly extracted AST model declarations to identify renamed models.
    Identifies renames when Python class_name matches but _name changed.
    """
    clean_fp = str(Path(filepath).resolve())
    renames: List[SymbolRename] = []

    # Find existing model nodes in G for this filepath
    existing_model_nodes: Dict[str, Dict[str, Any]] = {}
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

    # Map existing class_name -> node_id
    class_to_old_node: Dict[str, str] = {}
    for node_id, attrs in existing_model_nodes.items():
        c_name = attrs.get("class_name")
        if c_name:
            class_to_old_node[c_name] = node_id

    # Check new AST model declarations
    for m in new_models:
        if m.name and m.class_name in class_to_old_node:
            old_node_id = class_to_old_node[m.class_name]
            old_model_name = G.nodes[old_node_id].get("name") or old_node_id.replace("model:", "")
            new_model_name = m.name

            if old_model_name != new_model_name:
                new_node_id = f"model:{new_model_name}"
                renames.append(
                    SymbolRename(
                        old_symbol=old_node_id,
                        new_symbol=new_node_id,
                        symbol_type="model",
                        filepath=filepath,
                        class_name=m.class_name,
                        old_name=old_model_name,
                        new_name=new_model_name,
                    )
                )

    return renames


def refactor_rename_in_graph(
    G: nx.DiGraph,
    renames: List[SymbolRename],
) -> Tuple[nx.DiGraph, Dict[str, Any]]:
    """
    J43-J45: Perform graph refactoring for a list of detected symbol renames.
    Replaces node IDs in NetworkX graph, rewires all edges, preserves attributes,
    and returns (updated_G, summary_report).
    """
    if not renames:
        return G, {"renamed_count": 0, "rewired_edges_count": 0, "details": []}

    H = G.copy()
    rewired_edges_count = 0
    details = []

    for r in renames:
        old_id = r.old_symbol
        new_id = r.new_symbol

        if not H.has_node(old_id):
            _logger.warning("Rename target node %s not found in graph", old_id)
            continue

        # Preserve node attributes and update name
        attrs = dict(H.nodes[old_id])
        attrs["name"] = r.new_name or attrs.get("name")
        attrs["previous_names"] = attrs.get("previous_names", []) + [r.old_name]

        # Add new node
        H.add_node(new_id, **attrs)

        # Rewire incoming edges (predecessors -> new_id)
        for pred in list(H.predecessors(old_id)):
            edge_attrs = dict(H.get_edge_data(pred, old_id))
            H.add_edge(pred, new_id, **edge_attrs)
            rewired_edges_count += 1

        # Rewire outgoing edges (new_id -> successors)
        for succ in list(H.successors(old_id)):
            edge_attrs = dict(H.get_edge_data(old_id, succ))
            H.add_edge(new_id, succ, **edge_attrs)
            rewired_edges_count += 1

        # Remove old node
        H.remove_node(old_id)

        details.append({
            "old_symbol": old_id,
            "new_symbol": new_id,
            "class_name": r.class_name,
            "filepath": r.filepath,
        })
        _logger.info("Refactored graph node %s -> %s (class=%s)", old_id, new_id, r.class_name)

    summary = {
        "renamed_count": len(details),
        "rewired_edges_count": rewired_edges_count,
        "details": details,
    }
    return H, summary

# ── Symbol Resolver ──────────────────────────────────────────────────────

"""
code_intelligence/graph/symbol_resolver.py

Pass 1 & Pass 2 symbol resolution across all parsed Odoo modules.
"""

import logging
import re
from typing import Dict

from code_intelligence.utils import resolve_model_xmlref

from .integrity import _detect_inheritance_cycles
from .nodes import (
    CORE_BASE_MODULES,
    ParsedModule,
    ResolvedSymbolRegistry,
    UnresolvedCategory,
    UnresolvedReference,
)
from .integrity import topological_sort_modules

_logger = logging.getLogger(__name__)


def build_module_symbol_registry(modules_dict: Dict[str, ParsedModule]) -> ResolvedSymbolRegistry:
    """
    Pass 1 & Pass 2 symbol resolution across all parsed modules.
    Returns populated ResolvedSymbolRegistry with all cross-file references resolved.
    """
    registry = ResolvedSymbolRegistry()

    # Sort modules topologically by manifest dependencies
    load_order = topological_sort_modules(modules_dict)

    # ── PASS 1: Indexing Defined Symbols ──────────────────────────────────────
    for mod_name in load_order:
        mod = modules_dict.get(mod_name)
        if not mod:
            continue

        # 1. Index Python Models
        for decl in mod.models:
            model_key = decl.name
            if not model_key:
                # Extension without _name -> target is first _inherit item if present
                if decl.inherit:
                    model_key = decl.inherit[0]

            if model_key:
                if model_key not in registry.models:
                    registry.models[model_key] = []
                registry.models[model_key].append(decl)
                if model_key not in registry.model_modules:
                    registry.model_modules[model_key] = []
                registry.model_modules[model_key].append(mod_name)

        # 2. Index XML Groups with merge
        for grp in mod.groups:
            full_xml_id = grp.xml_id if "." in grp.xml_id else f"{mod_name}.{grp.xml_id}"
            existing = registry.groups.get(full_xml_id)
            if existing:
                grp = _merge_group(existing, grp)
            registry.groups[full_xml_id] = grp
            registry.groups[grp.xml_id] = grp

        # 3. Index XML Rules with merge
        for rule in mod.rules:
            full_xml_id = rule.xml_id if "." in rule.xml_id else f"{mod_name}.{rule.xml_id}"
            existing = registry.rules.get(full_xml_id)
            if existing:
                rule = _merge_rule(existing, rule)
            registry.rules[full_xml_id] = rule
            registry.rules[rule.xml_id] = rule

        # 4. Index Actions, Server Actions, Automations, Menuitems, Views
        for act in mod.actions:
            full_xml_id = act.xml_id if "." in act.xml_id else f"{mod_name}.{act.xml_id}"
            existing = registry.actions.get(full_xml_id)
            if existing:
                act = _merge_action(existing, act)
            registry.actions[full_xml_id] = act
            registry.actions[act.xml_id] = act

        for sa in mod.server_actions:
            full_xml_id = sa.xml_id if "." in sa.xml_id else f"{mod_name}.{sa.xml_id}"
            existing = registry.server_actions.get(full_xml_id)
            if existing:
                sa = _merge_server_action(existing, sa)
            registry.server_actions[full_xml_id] = sa
            registry.server_actions[sa.xml_id] = sa

        for ba in mod.base_automations:
            full_xml_id = ba.xml_id if "." in ba.xml_id else f"{mod_name}.{ba.xml_id}"
            registry.base_automations[full_xml_id] = ba
            registry.base_automations[ba.xml_id] = ba

        for menu in mod.menuitems:
            full_xml_id = menu.xml_id if "." in menu.xml_id else f"{mod_name}.{menu.xml_id}"
            registry.menuitems[full_xml_id] = menu
            registry.menuitems[menu.xml_id] = menu

        for view in mod.views:
            full_xml_id = view.xml_id if "." in view.xml_id else f"{mod_name}.{view.xml_id}"
            registry.views[full_xml_id] = view
            registry.views[view.xml_id] = view

    # ── PASS 2: Ordered Reference Resolution & Categorization ────────────────
    for mod_name in load_order:
        mod = modules_dict.get(mod_name)
        if not mod:
            continue

        # 1. Resolve Model Inheritance & Extensions
        for decl in mod.models:
            for parent_ref in decl.inherit:
                _resolve_model_reference(mod_name, decl.filepath, parent_ref, registry)

            for parent_ref, fk_field in decl.inherits.items():
                _resolve_model_reference(mod_name, decl.filepath, parent_ref, registry)

        # 2. Resolve Security Rules (model_id & groups_id)
        for rule in mod.rules:
            if rule.model_id:
                clean_model = resolve_model_xmlref(rule.model_id)
                _resolve_model_reference(mod_name, rule.filepath, clean_model, registry)

            for grp_ref in rule.groups_id:
                _resolve_group_reference(mod_name, rule.filepath, grp_ref, registry)

        # 3. Resolve Group Implied Hierarchy
        for grp in mod.groups:
            for parent_grp_ref in grp.implied_ids:
                _resolve_group_reference(mod_name, grp.filepath, parent_grp_ref, registry)

    # ── Cycle Detection ──────────────────────────────────────────────
    _detect_inheritance_cycles(registry)

    return registry


def _resolve_model_reference(
    mod_name: str, filepath: str, model_ref: str, registry: ResolvedSymbolRegistry
):
    """Resolve model reference or record as categorized unresolved reference."""
    if model_ref in registry.models:
        return

    category = _categorize_unresolved(mod_name, model_ref)
    registry.unresolved_references.append(
        UnresolvedReference(
            source_module=mod_name,
            source_file=filepath,
            symbol_ref=model_ref,
            ref_type="model",
            category=category,
            detail=f"Model '{model_ref}' referenced in {mod_name} not found in index."
        )
    )


def _resolve_group_reference(
    mod_name: str, filepath: str, group_ref: str, registry: ResolvedSymbolRegistry
):
    """Resolve group reference or record as categorized unresolved reference."""
    if group_ref in registry.groups:
        return

    full_ref = group_ref if "." in group_ref else f"{mod_name}.{group_ref}"
    if full_ref in registry.groups:
        return

    category = _categorize_unresolved(mod_name, group_ref)
    registry.unresolved_references.append(
        UnresolvedReference(
            source_module=mod_name,
            source_file=filepath,
            symbol_ref=group_ref,
            ref_type="group",
            category=category,
            detail=f"Group '{group_ref}' referenced in {mod_name} not found in index."
        )
    )


def _categorize_unresolved(mod_name: str, symbol_ref: str) -> UnresolvedCategory:
    """Categorize an unresolved symbol reference."""
    if "." in symbol_ref:
        prefix = symbol_ref.split(".")[0]
        if prefix in CORE_BASE_MODULES:
            return UnresolvedCategory.CORE_ODOO_OUT_OF_SCOPE
        elif not re.match(r"^[a-zA-Z0-9_\.]+$", symbol_ref):
            return UnresolvedCategory.PROBABLE_TYPO

    if symbol_ref.startswith("base.") or symbol_ref.startswith("mail."):
        return UnresolvedCategory.CORE_ODOO_OUT_OF_SCOPE
    elif symbol_ref.count(".") > 2 or " " in symbol_ref:
        return UnresolvedCategory.PROBABLE_TYPO
    else:
        return UnresolvedCategory.ABSENT_FROM_CORPUS


__all__ = [
    "build_module_symbol_registry",
    "_resolve_model_reference",
    "_resolve_group_reference",
    "_categorize_unresolved",
]
