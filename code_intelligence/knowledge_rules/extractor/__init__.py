"""
code_intelligence/extractor/__init__.py

Central package re-exporting all code intelligence extractors:
- Python AST extractor
- XML extractors (rules, groups, actions, views, menus, fields, automations, crons)
- CSV ACL extractor
- JS/OWL security check extractor
- Manifest parser
"""

from .csv_extractor import (
    OdooAccessEntry,
    _parse_perm,
    parse_access_control_csv,
)
from .js_extractor import (
    JS_HAS_GROUP_PATTERN,
    OWL_T_IF_HAS_GROUP_PATTERN,
    SESSION_HAS_GROUP_PATTERN,
    OdooClientGroupCheck,
    parse_client_group_checks,
)
from .manifest_parser import (
    KNOWN_CORE_MODULE_DEPENDS,
    MissingManifestError,
    OdooManifest,
    parse_manifest,
    synthesize_fallback_manifest,
)
from .python_extractor import (
    OdooClassVisitor,
    extract_odoo_models_from_file,
)
from .python_models import (
    ModelRelationType,
    OdooFieldDeclaration,
    OdooMethodDecoration,
    OdooMethodDeclaration,
    OdooModelDeclaration,
)
from .xml_actions import (
    parse_actions_from_xml,
    parse_base_automations_from_xml,
    parse_server_actions_from_xml,
)
from .xml_models import (
    OdooActionRecord,
    OdooBaseAutomationRecord,
    OdooFormButton,
    OdooGroupRecord,
    OdooMenuItemRecord,
    OdooRuleRecord,
    OdooServerActionRecord,
    OdooViewRecord,
    OdooXmlFieldRecord,
    extract_refs_from_eval,
    parse_eval_bool,
)
from .xml_rules_groups import (
    parse_groups_from_xml,
    parse_ir_rules_from_xml,
)
from .xml_views import (
    _extract_buttons_from_arch_elem,
    parse_menuitems_from_xml,
    parse_views_from_xml,
    parse_xml_fields_from_xml,
)

__all__ = [
    # Python
    "ModelRelationType",
    "OdooFieldDeclaration",
    "OdooMethodDecoration",
    "OdooMethodDeclaration",
    "OdooModelDeclaration",
    "OdooClassVisitor",
    "extract_odoo_models_from_file",
    # XML
    "OdooRuleRecord",
    "OdooGroupRecord",
    "OdooActionRecord",
    "OdooServerActionRecord",
    "OdooBaseAutomationRecord",
    "OdooXmlFieldRecord",
    "OdooMenuItemRecord",
    "OdooFormButton",
    "OdooViewRecord",
    "parse_eval_bool",
    "extract_refs_from_eval",
    "parse_ir_rules_from_xml",
    "parse_groups_from_xml",
    "parse_actions_from_xml",
    "parse_server_actions_from_xml",
    "parse_base_automations_from_xml",
    "parse_xml_fields_from_xml",
    "parse_menuitems_from_xml",
    "_extract_buttons_from_arch_elem",
    "parse_views_from_xml",
    # CSV
    "OdooAccessEntry",
    "_parse_perm",
    "parse_access_control_csv",
    # JS
    "OdooClientGroupCheck",
    "JS_HAS_GROUP_PATTERN",
    "SESSION_HAS_GROUP_PATTERN",
    "OWL_T_IF_HAS_GROUP_PATTERN",
    "parse_client_group_checks",
    # Manifest
    "OdooManifest",
    "MissingManifestError",
    "KNOWN_CORE_MODULE_DEPENDS",
    "parse_manifest",
    "synthesize_fallback_manifest",
]
