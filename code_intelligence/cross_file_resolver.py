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
    OdooServerActionRecord,
    OdooBaseAutomationRecord,
    OdooMenuItemRecord,
    OdooViewRecord,
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_server_actions_from_xml,
    parse_base_automations_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)
from code_intelligence.csv_extractor import (
    OdooAccessEntry,
    parse_access_control_csv,
)
from code_intelligence.utils import resolve_model_xmlref

_logger = logging.getLogger(__name__)


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
    server_actions: List[OdooServerActionRecord] = field(default_factory=list)
    base_automations: List[OdooBaseAutomationRecord] = field(default_factory=list)
    menuitems: List[OdooMenuItemRecord] = field(default_factory=list)
    views: List[OdooViewRecord] = field(default_factory=list)
    acl_entries: List[OdooAccessEntry] = field(default_factory=list)


@dataclass
class ResolvedSymbolRegistry:
    # Key = model_name (e.g. "sale.order"), Value = List of declarations across modules
    models: Dict[str, List[OdooModelDeclaration]] = field(default_factory=dict)
    # Bloc 8 (J28-29): Key = model_name, Value = List of module names, in the
    # SAME order as models[model_name] (one module name per declaration) --
    # lets graph_builder create one DEFINED_IN edge per real declaration
    # site instead of arbitrarily picking decls[0]'s filepath.
    model_modules: Dict[str, List[str]] = field(default_factory=dict)
    # Key = full_xml_id (e.g. "base.group_user" or "sale.group_sale_manager"), Value = Record
    groups: Dict[str, OdooGroupRecord] = field(default_factory=dict)
    rules: Dict[str, OdooRuleRecord] = field(default_factory=dict)
    actions: Dict[str, OdooActionRecord] = field(default_factory=dict)
    server_actions: Dict[str, OdooServerActionRecord] = field(default_factory=dict)
    base_automations: Dict[str, OdooBaseAutomationRecord] = field(default_factory=dict)
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

    def visit(m_name: str, chain: List[str]):
        if m_name in chain:
            _logger.warning("Circular dependency detected in manifests: %s", " -> ".join(chain + [m_name]))
            return
        if m_name not in visited:
            visited.add(m_name)
            mod = modules_dict.get(m_name)
            if mod and mod.manifest:
                for dep in mod.manifest.depends:
                    visit(dep, chain + [m_name])
            elif mod is not None:
                # 2026-08-06 fix: this used to be silent (`if mod and
                # mod.manifest` simply False for manifest=None), which let a
                # module with real, unresolved dependencies get appended to
                # load_order by filesystem/dict iteration order instead of by
                # its actual depends -- corrupting load_order and, downstream,
                # every method-override execution order derived from it (see
                # rag/graph.py::_load_module and manifest_parser.py::
                # MissingManifestError for the full fix). rag/graph.py's real
                # corpus loader now always supplies a manifest (real, hardcoded
                # fallback for known core modules, or raises) so this branch
                # should be unreachable there; it stays reachable here only for
                # callers/tests that intentionally construct
                # ParsedModule(manifest=None, ...) for cases where dependency
                # order genuinely doesn't matter (e.g. a single isolated
                # module) -- for those this module is still, correctly,
                # treated as a dependency-free leaf, just no longer silently.
                _logger.warning(
                    "Module '%s' has no manifest (or no manifest.depends) -- "
                    "treating it as having NO dependencies for load-order "
                    "purposes. If '%s' actually depends on other modules, this "
                    "will silently produce a wrong load_order and a wrong "
                    "method-override execution order for any method it shares "
                    "with those dependencies.",
                    m_name, m_name,
                )
            sorted_modules.append(m_name)

    for name in modules_dict:
        visit(name, [])

    return sorted_modules


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
                # Bloc 8 (J28-29): record mod_name in lockstep with the decl
                # just appended above -- same index in both lists -- so
                # graph_builder can zip them back together per-declaration
                # instead of guessing a module from decl.filepath.
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

        # 4. Index Actions, Server Actions, Automations, Menuitems, Views with merge for actions & server_actions
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

        # base_automations, menuitems, views: left as is (no known extension bug)
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
    Note: In-place model extensions (_inherit = 'model.name') where parent == model_name
    are excluded from cycle detection.
    """
    # Build model dependency graph excluding self-extensions (in-place module extensions)
    inheritance_graph: Dict[str, List[str]] = {}
    for model_name, decls in registry.models.items():
        parents = []
        for decl in decls:
            parents.extend(decl.inherit)
            parents.extend(decl.inherits.keys())
        # Exclude self-references (in-place _inherit = 'same.model')
        inheritance_graph[model_name] = [p for p in parents if p != model_name]

    visited: Set[str] = set()
    rec_stack: Set[str] = set()

    def dfs(node: str, path: List[str]):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for parent in inheritance_graph.get(node, []):
            if parent == node:
                continue
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
