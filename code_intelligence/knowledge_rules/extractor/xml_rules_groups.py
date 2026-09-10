"""
code_intelligence/extractor/xml_rules_groups.py

XML parsers for ir.rule and res.groups declarations.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from .xml_models import (
    OdooGroupRecord,
    OdooRuleRecord,
    extract_refs_from_eval,
    parse_eval_bool,
)

_logger = logging.getLogger(__name__)


def parse_ir_rules_from_xml(filepath: Path) -> List[OdooRuleRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.rule"> declarations.
    """
    if not filepath.exists():
        _logger.warning("XML file does not exist: %s", filepath)
        return []

    rules: List[OdooRuleRecord] = []

    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.splitlines()
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s: %s", filepath, e)
        return []

    for record in root.findall(".//record"):
        model_attr = record.attrib.get("model")
        if model_attr != "ir.rule":
            continue

        xml_id = record.attrib.get("id", "")

        # Line number estimation by looking up id="xml_id"
        lineno = 1
        if xml_id:
            for idx, line in enumerate(lines, 1):
                if f'id="{xml_id}"' in line or f"id='{xml_id}'" in line:
                    lineno = idx
                    break

        rule = OdooRuleRecord(
            xml_id=xml_id,
            filepath=str(filepath),
            lineno=lineno,
        )

        for field_elem in record.findall("field"):
            field_name = field_elem.attrib.get("name")
            if not field_name:
                continue

            field_text = (field_elem.text or "").strip()
            field_ref = field_elem.attrib.get("ref")
            field_eval = field_elem.attrib.get("eval")

            if field_name == "name":
                rule.name = field_text
            elif field_name == "model_id":
                if field_ref:
                    rule.model_id = field_ref
                elif field_eval:
                    refs = extract_refs_from_eval(field_eval)
                    if refs:
                        rule.model_id = refs[0]
                elif field_text:
                    rule.model_id = field_text
            elif field_name == "domain_force":
                rule.domain_force = field_text
            elif field_name in {"groups", "groups_id"}:
                groups_list = []
                if field_ref:
                    groups_list.append(field_ref)
                if field_eval:
                    eval_refs = extract_refs_from_eval(field_eval)
                    groups_list.extend(eval_refs)
                rule.groups_id.extend(groups_list)
            elif field_name == "perm_read":
                rule.perm_read = parse_eval_bool(field_eval, field_text, default=True)
            elif field_name == "perm_write":
                rule.perm_write = parse_eval_bool(field_eval, field_text, default=True)
            elif field_name == "perm_create":
                rule.perm_create = parse_eval_bool(field_eval, field_text, default=True)
            elif field_name == "perm_unlink":
                rule.perm_unlink = parse_eval_bool(field_eval, field_text, default=True)
            elif field_name == "active":
                rule.active = parse_eval_bool(field_eval, field_text, default=True)

        rules.append(rule)

    return rules


def parse_groups_from_xml(filepath: Path) -> List[OdooGroupRecord]:
    """
    Parse an Odoo XML file and extract all <record model="res.groups"> declarations.
    """
    if not filepath.exists():
        return []

    groups: List[OdooGroupRecord] = []
    try:
        content = filepath.read_text(encoding="utf-8")
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s for groups: %s", filepath, e)
        return []

    for record in root.findall(".//record"):
        if record.attrib.get("model") != "res.groups":
            continue

        xml_id = record.attrib.get("id", "")
        group = OdooGroupRecord(
            xml_id=xml_id,
            filepath=str(filepath),
            lineno=0,
        )

        for field_elem in record.findall("field"):
            field_name = field_elem.attrib.get("name")
            if not field_name:
                continue

            field_text = (field_elem.text or "").strip()
            field_ref = field_elem.attrib.get("ref")
            field_eval = field_elem.attrib.get("eval")

            if field_name == "name":
                group.name = field_text
            elif field_name == "category_id":
                if field_ref:
                    group.category_id = field_ref
                elif field_eval:
                    refs = extract_refs_from_eval(field_eval)
                    if refs:
                        group.category_id = refs[0]
            elif field_name in {"implied_ids", "implied"}:
                implied = []
                if field_ref:
                    implied.append(field_ref)
                if field_eval:
                    implied.extend(extract_refs_from_eval(field_eval))
                group.implied_ids.extend(implied)
            elif field_name == "comment":
                group.comment = field_text

        groups.append(group)

    return groups
