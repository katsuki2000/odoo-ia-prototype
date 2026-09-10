"""
code_intelligence/extractor/xml_extractor.py

Aggregated XML extractor interface re-exporting records and parser functions.
"""

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
]
