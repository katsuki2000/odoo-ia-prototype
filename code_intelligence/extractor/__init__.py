"""Odoo source code extractors."""

from .csv import OdooAccessEntry, parse_access_control_csv
from .js import (
    JS_HAS_GROUP_PATTERN,
    OWL_T_IF_HAS_GROUP_PATTERN,
    SESSION_HAS_GROUP_PATTERN,
    OdooClientGroupCheck,
    parse_client_group_checks,
)
from .manifest import (
    KNOWN_CORE_MODULE_DEPENDS,
    MissingManifestError,
    OdooManifest,
    parse_manifest,
    synthesize_fallback_manifest,
)
from .python import (
    ModelRelationType,
    OdooClassVisitor,
    OdooFieldDeclaration,
    OdooMethodDecoration,
    OdooMethodDeclaration,
    OdooModelDeclaration,
    extract_odoo_models_from_file,
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
    parse_xml_root,
)
from .xml import (
    parse_actions_from_xml,
    parse_base_automations_from_xml,
    parse_server_actions_from_xml,
    parse_groups_from_xml,
    parse_ir_rules_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
    parse_xml_fields_from_xml,
)
