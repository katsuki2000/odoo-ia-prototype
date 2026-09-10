"""
code_intelligence/graph/models.py

Data models and registries for cross-file Odoo symbol resolution and graph building.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from code_intelligence.extractor.manifest_parser import OdooManifest
from code_intelligence.extractor.python_extractor import OdooModelDeclaration
from code_intelligence.extractor.xml_extractor import (
    OdooActionRecord,
    OdooBaseAutomationRecord,
    OdooGroupRecord,
    OdooMenuItemRecord,
    OdooRuleRecord,
    OdooServerActionRecord,
    OdooViewRecord,
)
from code_intelligence.extractor.csv_extractor import OdooAccessEntry


class UnresolvedCategory(Enum):
    ABSENT_FROM_CORPUS = "absent_from_corpus"
    CORE_ODOO_OUT_OF_SCOPE = "core_odoo_out_of_scope"
    PROBABLE_TYPO = "probable_typo"


@dataclass
class UnresolvedReference:
    source_module: str
    source_file: str
    symbol_ref: str
    ref_type: str  # "model", "group", "rule", "action"
    category: UnresolvedCategory
    detail: str = ""


@dataclass
class ParsedModule:
    manifest: Optional[OdooManifest]
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
    # Key = model_name, Value = List of module names matching models[model_name] order
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
    resolved_inheritance: Dict[str, List[str]] = field(default_factory=dict)  # model -> parent_models
    unresolved_references: List[UnresolvedReference] = field(default_factory=list)
    detected_cycles: List[List[str]] = field(default_factory=list)


CORE_BASE_MODULES = {
    "base", "mail", "portal", "utm", "bus", "web", "product", "account", "sale", "stock"
}


__all__ = [
    "UnresolvedCategory",
    "UnresolvedReference",
    "ParsedModule",
    "ResolvedSymbolRegistry",
    "CORE_BASE_MODULES",
]
