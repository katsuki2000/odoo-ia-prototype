"""
code_intelligence/cross_file_resolver.py

Two-Pass Cross-File Reference Resolver for Odoo Code Intelligence.
Implements Story A2.1:
  - A2.1.1: Topological sorting of modules by manifest depends + Pass 1 symbol indexation.
  - A2.1.2: Pass 2 ordered reference resolution (model inheritance, fields, security rules, group hierarchy).
  - A2.1.3: Categorized unresolved reference registry (absent_from_corpus, core_odoo_out_of_scope, probable_typo).
  - A2.1.4: Inheritance cycle detection with visited tracking.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import logging

from code_intelligence.manifest_parser import OdooManifest, parse_manifest
from code_intelligence.python_extractor import (
    OdooModelDeclaration,
    extract_odoo_models_from_file,
)
from code_intelligence.xml_extractor import (
    OdooRuleRecord,
    OdooGroupRecord,
    OdooActionRecord,
    OdooMenuItemRecord,
    OdooViewRecord,
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)
from code_intelligence.csv_extractor import (
    OdooAccessEntry,
    parse_access_control_csv,
)

_logger = logging.getLogger(__name__)


class UnresolvedCategory(Enum):
    ABSENT_FROM_CORPUS = "absent_from_corpus"
    CORE_ODOO_OUT_OF_SCOPE = "core_odoo_out_of_scope"
    PROBABLE_TYPO = "probable_typo"


@dataclass
class UnresolvedReference:
    source_module: str
    source_file: str
    symbol_ref: str
    ref_type: str # "model", "group", "rule", "action"
    category: UnresolvedCategory
    detail: str = ""


@dataclass
class ParsedModule:
    manifest: OdooManifest
    models: List[OdooModelDeclaration] = field(default_factory=list)
    rules: List[OdooRuleRecord] = field(default_factory=list)
    groups: List[OdooGroupRecord] = field(default_factory=list)
    actions: List[OdooActionRecord] = field(default_factory=list)
    menuitems: List[OdooMenuItemRecord] = field(default_factory=list)
    views: List[OdooViewRecord] = field(default_factory=list)
    acl_entries: List[OdooAccessEntry] = field(default_factory=list)


@dataclass
class ResolvedSymbolRegistry:
    # Key = model_name (e.g. "sale.order"), Value = List of declarations across modules
    models: Dict[str, List[OdooModelDeclaration]] = field(default_factory=dict)
    # Key = full_xml_id (e.g. "base.group_user" or "sale.group_sale_manager"), Value = Record
    groups: Dict[str, OdooGroupRecord] = field(default_factory=dict)
    rules: Dict[str, OdooRuleRecord] = field(default_factory=dict)
    actions: Dict[str, OdooActionRecord] = field(default_factory=dict)
    menuitems: Dict[str, OdooMenuItemRecord] = field(default_factory=dict)
    views: Dict[str, OdooViewRecord] = field(default_factory=dict)

    # Resolution & Unresolved tracking
    resolved_inheritance: Dict[str, List[str]] = field(default_factory=dict) # model -> parent_models
    unresolved_references: List[UnresolvedReference] = field(default_factory=list)
    detected_cycles: List[List[str]] = field(default_factory=list)


CORE_BASE_MODULES = {
    "base", "mail", "portal", "utm", "bus", "web", "product", "account", "sale", "stock"
}


def topological_sort_modules(modules_dict: Dict[str, ParsedModule]) -> List[str]:
    """
    Topologically sort module names based on manifest 'depends'.
    Ensures parent modules are indexed before dependent modules.
    """
    sorted_modules: List[str] = []
    visited: Set[str] = set()
    permanently_visited: Set[str] = set()

    def visit(mod_name: str):
        if mod_name in permanently_visited:
            return
        if mod_name in visited:
            _logger.warning("Circular module dependency detected involving: %s", mod_name)
            return

        visited.add(mod_name)
        module = modules_dict.get(mod_name)
        if module and module.manifest:
            for dep in module.manifest.depends:
                if dep in modules_dict:
                    visit(dep)

        visited.remove(mod_name)
        permanently_visited.add(mod_name)
        sorted_modules.append(mod_name)

    for mod_name in sorted(modules_dict.keys()):
        if mod_name not in permanently_visited:
            visit(mod_name)

    return sorted_modules


def build_module_symbol_registry(modules_dict: Dict[str, ParsedModule]) -> ResolvedSymbolRegistry:
    """
    Two-Pass Cross-File Reference Resolver.
    Pass 1: Topological load order indexation of defined symbols.
    Pass 2: Ordered reference resolution, unresolved reference categorization, and cycle detection.
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

        # 2. Index XML Groups
        for grp in mod.groups:
            full_xml_id = grp.xml_id if "." in grp.xml_id else f"{mod_name}.{grp.xml_id}"
            registry.groups[full_xml_id] = grp
            registry.groups[grp.xml_id] = grp

        # 3. Index XML Rules
        for rule in mod.rules:
            full_xml_id = rule.xml_id if "." in rule.xml_id else f"{mod_name}.{rule.xml_id}"
            registry.rules[full_xml_id] = rule
            registry.rules[rule.xml_id] = rule

        # 4. Index Actions, Menuitems, Views
        for act in mod.actions:
            full_xml_id = act.xml_id if "." in act.xml_id else f"{mod_name}.{act.xml_id}"
            registry.actions[full_xml_id] = act
            registry.actions[act.xml_id] = act

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
                # Strip model_ prefix if present (e.g. model_sale_order -> sale.order)
                raw_model = rule.model_id
                clean_model = raw_model.replace("model_", "").replace("_", ".") if raw_model.startswith("model_") else raw_model
                _resolve_model_reference(mod_name, rule.filepath, clean_model, registry)

            for grp_ref in rule.groups_id:
                _resolve_group_reference(mod_name, rule.filepath, grp_ref, registry)

        # 3. Resolve Group Implied Hierarchy
        for grp in mod.groups:
            for parent_grp_ref in grp.implied_ids:
                _resolve_group_reference(mod_name, grp.filepath, parent_grp_ref, registry)

    # ── Cycle Detection (A2.1.4) ──────────────────────────────────────────────
    _detect_inheritance_cycles(registry)

    return registry


def _resolve_model_reference(
    mod_name: str, filepath: str, model_ref: str, registry: ResolvedSymbolRegistry
):
    """Resolve model reference or record as categorized unresolved reference."""
    if model_ref in registry.models:
        return

    # Categorize unresolved model reference
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

    # Try matching with module prefix
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


def _detect_inheritance_cycles(registry: ResolvedSymbolRegistry):
    """
    Detect inheritance cycles across models using visited: set().
    Fills registry.detected_cycles with detected cycle paths.
    """
    # Build model dependency graph
    inheritance_graph: Dict[str, List[str]] = {}
    for model_name, decls in registry.models.items():
        parents = []
        for decl in decls:
            parents.extend(decl.inherit)
            parents.extend(decl.inherits.keys())
        inheritance_graph[model_name] = parents

    visited: Set[str] = set()
    rec_stack: Set[str] = set()

    def dfs(node: str, path: List[str]):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for parent in inheritance_graph.get(node, []):
            if parent not in visited:
                dfs(parent, path)
            elif parent in rec_stack:
                cycle_start_idx = path.index(parent)
                cycle_path = path[cycle_start_idx:] + [parent]
                _logger.warning("Inheritance cycle detected: %s", " -> ".join(cycle_path))
                registry.detected_cycles.append(cycle_path)

        path.pop()
        rec_stack.remove(node)

    for model_name in list(inheritance_graph.keys()):
        if model_name not in visited:
            dfs(model_name, [])
