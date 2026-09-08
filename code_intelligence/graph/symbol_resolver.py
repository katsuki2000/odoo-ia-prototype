"""
code_intelligence/graph/symbol_resolver.py

Pass 1 & Pass 2 symbol resolution across all parsed Odoo modules.
"""

import logging
import re
from typing import Dict

from code_intelligence.utils import resolve_model_xmlref

from .cycle_detector import _detect_inheritance_cycles
from .models import (
    CORE_BASE_MODULES,
    ParsedModule,
    ResolvedSymbolRegistry,
    UnresolvedCategory,
    UnresolvedReference,
)
from .symbol_merger import (
    _merge_action,
    _merge_group,
    _merge_rule,
    _merge_server_action,
)
from .topological_sort import topological_sort_modules

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
