"""
code_intelligence/xml_extractor.py

AST/XML-based extractor for Odoo XML files.
Implements Task A1.2.1: Parser ir.rule (domain_force, groups_id, model_id, perm_read/write/create/unlink).
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import logging

_logger = logging.getLogger(__name__)


@dataclass
class OdooRuleRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    domain_force: str = ""
    groups_id: List[str] = field(default_factory=list)
    perm_read: bool = True
    perm_write: bool = True
    perm_create: bool = True
    perm_unlink: bool = True
    active: bool = True


@dataclass
class OdooGroupRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    category_id: str = ""
    implied_ids: List[str] = field(default_factory=list)
    comment: str = ""


@dataclass
class OdooActionRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    res_model: str = ""
    view_mode: str = ""
    groups_id: List[str] = field(default_factory=list)


@dataclass
class OdooServerActionRecord:
    """Represents an ir.actions.server record extracted from XML data files."""
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    state: str = "code"
    code: str = ""
    groups_id: List[str] = field(default_factory=list)


@dataclass
class OdooBaseAutomationRecord:
    """Represents a base.automation record extracted from XML data files."""
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    trigger: str = ""
    action_server_ids: List[str] = field(default_factory=list)


@dataclass
class OdooXmlFieldRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model: str = ""
    field_description: str = ""
    ttype: str = ""
    relation: str = ""


@dataclass
class OdooMenuItemRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    parent: str = ""
    action: str = ""
    sequence: int = 10
    groups: List[str] = field(default_factory=list)


@dataclass
class OdooFormButton:
    name: str
    string: str
    type: str = "object"
    states: str = ""
    groups: List[str] = field(default_factory=list)


@dataclass
class OdooViewRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model: str = ""
    view_type: str = "form"
    buttons: List[OdooFormButton] = field(default_factory=list)


def parse_eval_bool(eval_attr: Optional[str], text_content: Optional[str], default: bool = True) -> bool:
    """Parse boolean value for Odoo permissions from eval attribute or text content."""
    if eval_attr is not None:
        eval_str = eval_attr.strip()
        if eval_str in {"0", "False", "0.0"}:
            return False
        elif eval_str in {"1", "True", "1.0"}:
            return True

    if text_content is not None and text_content.strip():
        text_str = text_content.strip()
        if text_str in {"0", "False"}:
            return False
        elif text_str in {"1", "True"}:
            return True

    return default


def extract_refs_from_eval(eval_str: str) -> List[str]:
    """Extract all ref('xml_id') values from an eval string."""
    if not eval_str:
        return []
    # Pattern to match ref('xml_id') or ref("xml_id")
    pattern = r"ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"
    return re.findall(pattern, eval_str)


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


def parse_actions_from_xml(filepath: Path) -> List[OdooActionRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.actions.act_window"> declarations.
    """
    if not filepath.exists():
        return []

    actions: List[OdooActionRecord] = []
    try:
        content = filepath.read_text(encoding="utf-8")
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s for actions: %s", filepath, e)
        return []

    for record in root.findall(".//record"):
        if record.attrib.get("model") != "ir.actions.act_window":
            continue

        xml_id = record.attrib.get("id", "")
        action = OdooActionRecord(
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
                action.name = field_text
            elif field_name in {"res_model", "model"}:
                action.res_model = field_text or field_ref or ""
            elif field_name == "view_mode":
                action.view_mode = field_text
            elif field_name in {"groups", "groups_id"}:
                grp_list = []
                if field_ref:
                    grp_list.append(field_ref)
                if field_eval:
                    grp_list.extend(extract_refs_from_eval(field_eval))
                action.groups_id.extend(grp_list)

        actions.append(action)

    return actions


def parse_xml_fields_from_xml(filepath: Path) -> List[OdooXmlFieldRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.model.fields"> declarations.
    """
    if not filepath.exists():
        return []

    fields_list: List[OdooXmlFieldRecord] = []
    try:
        content = filepath.read_text(encoding="utf-8")
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s for xml fields: %s", filepath, e)
        return []

    for record in root.findall(".//record"):
        if record.attrib.get("model") != "ir.model.fields":
            continue

        xml_id = record.attrib.get("id", "")
        f_rec = OdooXmlFieldRecord(xml_id=xml_id, filepath=str(filepath), lineno=0)

        for field_elem in record.findall("field"):
            field_name = field_elem.attrib.get("name")
            if not field_name:
                continue

            field_text = (field_elem.text or "").strip()
            field_ref = field_elem.attrib.get("ref")

            if field_name == "name":
                f_rec.name = field_text
            elif field_name in {"model", "model_id"}:
                f_rec.model = field_text or field_ref or ""
            elif field_name == "field_description":
                f_rec.field_description = field_text
            elif field_name == "ttype":
                f_rec.ttype = field_text
            elif field_name == "relation":
                f_rec.relation = field_text or field_ref or ""

        fields_list.append(f_rec)

    return fields_list


def parse_menuitems_from_xml(filepath: Path) -> List[OdooMenuItemRecord]:
    """
    Parse an Odoo XML file and extract all <menuitem> elements and <record model="ir.ui.menu"> records.
    """
    if not filepath.exists():
        return []

    menuitems: List[OdooMenuItemRecord] = []
    try:
        content = filepath.read_text(encoding="utf-8")
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s for menuitems: %s", filepath, e)
        return []

    # 1. Concise <menuitem .../> elements
    for elem in root.findall(".//menuitem"):
        xml_id = elem.attrib.get("id", "")
        name = elem.attrib.get("name", "")
        parent = elem.attrib.get("parent", "")
        action = elem.attrib.get("action", "")
        seq_str = elem.attrib.get("sequence", "10")
        groups_raw = elem.attrib.get("groups", "")

        try:
            seq = int(seq_str)
        except ValueError:
            seq = 10

        groups_list = [g.strip() for g in groups_raw.split(",") if g.strip()]

        menuitems.append(
            OdooMenuItemRecord(
                xml_id=xml_id,
                filepath=str(filepath),
                lineno=0,
                name=name,
                parent=parent,
                action=action,
                sequence=seq,
                groups=groups_list,
            )
        )

    # 2. Record form: <record model="ir.ui.menu">
    for record in root.findall(".//record"):
        if record.attrib.get("model") != "ir.ui.menu":
            continue

        xml_id = record.attrib.get("id", "")
        menu = OdooMenuItemRecord(xml_id=xml_id, filepath=str(filepath), lineno=0)

        for field_elem in record.findall("field"):
            field_name = field_elem.attrib.get("name")
            if not field_name:
                continue

            field_text = (field_elem.text or "").strip()
            field_ref = field_elem.attrib.get("ref")
            field_eval = field_elem.attrib.get("eval")

            if field_name == "name":
                menu.name = field_text
            elif field_name in {"parent", "parent_id"}:
                menu.parent = field_ref or field_text
            elif field_name in {"action", "action_id"}:
                menu.action = field_ref or field_text
            elif field_name == "sequence":
                try:
                    menu.sequence = int(field_text)
                except ValueError:
                    menu.sequence = 10
            elif field_name in {"groups", "groups_id"}:
                grp_list = []
                if field_ref:
                    grp_list.append(field_ref)
                if field_eval:
                    grp_list.extend(extract_refs_from_eval(field_eval))
                if field_text:
                    grp_list.extend([g.strip() for g in field_text.split(",") if g.strip()])
                menu.groups.extend(grp_list)

        menuitems.append(menu)

    return menuitems


def parse_views_from_xml(filepath: Path) -> List[OdooViewRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.ui.view"> records with form buttons.
    """
    if not filepath.exists():
        return []

    views: List[OdooViewRecord] = []
    try:
        content = filepath.read_text(encoding="utf-8")
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s for views: %s", filepath, e)
        return []

    for record in root.findall(".//record"):
        if record.attrib.get("model") != "ir.ui.view":
            continue

        xml_id = record.attrib.get("id", "")
        view = OdooViewRecord(xml_id=xml_id, filepath=str(filepath), lineno=0)

        for field_elem in record.findall("field"):
            field_name = field_elem.attrib.get("name")
            if not field_name:
                continue

            field_text = (field_elem.text or "").strip()
            field_ref = field_elem.attrib.get("ref")

            if field_name == "name":
                view.name = field_text
            elif field_name in {"model", "res_model"}:
                view.model = field_text or field_ref or ""
            elif field_name == "type":
                view.view_type = field_text
            elif field_name == "arch":
                buttons = _extract_buttons_from_arch_elem(field_elem)
                view.buttons.extend(buttons)

        views.append(view)

    return views


def _extract_buttons_from_arch_elem(arch_elem: ET.Element) -> List[OdooFormButton]:
    """Extract all <button> elements from an arch field XML element."""
    buttons: List[OdooFormButton] = []
    for btn in arch_elem.findall(".//button"):
        btn_name = btn.attrib.get("name", "")
        btn_string = btn.attrib.get("string", "")
        btn_type = btn.attrib.get("type", "object")
        btn_states = btn.attrib.get("states", "")
        btn_invisible = btn.attrib.get("invisible", "")
        btn_groups_raw = btn.attrib.get("groups", "")

        # Handle Odoo 17 invisible="state not in ['draft', 'sent']" syntax if states attr is missing
        if not btn_states and btn_invisible and "state" in btn_invisible:
            extracted_states = re.findall(r"['\"]([a-zA-Z0-9_]+)['\"]", btn_invisible)
            if extracted_states:
                btn_states = ",".join(extracted_states)

        btn_groups = [g.strip() for g in btn_groups_raw.split(",") if g.strip()]

        if btn_name or btn_string:
            buttons.append(
                OdooFormButton(
                    name=btn_name,
                    string=btn_string,
                    type=btn_type,
                    states=btn_states,
                    groups=btn_groups,
                )
            )
    return buttons


def parse_server_actions_from_xml(filepath: Path) -> List[OdooServerActionRecord]:
    """
    Story S2.3: Parse an Odoo XML file and extract all <record model="ir.actions.server"> declarations.
    Captures the 'code' field content that contains executable Python logic.
    """
    if not filepath.exists():
        _logger.warning("XML file does not exist: %s", filepath)
        return []

    actions: List[OdooServerActionRecord] = []

    try:
        content = filepath.read_text(encoding="utf-8")
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s: %s", filepath, e)
        return []

    for record in root.findall(".//record"):
        model_attr = record.attrib.get("model")
        if model_attr != "ir.actions.server":
            continue

        xml_id = record.attrib.get("id", "")
        sa = OdooServerActionRecord(
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
                sa.name = field_text
            elif field_name == "model_id":
                if field_ref:
                    sa.model_id = field_ref
                elif field_eval:
                    refs = extract_refs_from_eval(field_eval)
                    if refs:
                        sa.model_id = refs[0]
                elif field_text:
                    sa.model_id = field_text
            elif field_name == "state":
                sa.state = field_text
            elif field_name == "code":
                # Preserve the full code content including whitespace
                sa.code = field_elem.text or ""
            elif field_name in {"groups", "groups_id"}:
                if field_ref:
                    sa.groups_id.append(field_ref)
                if field_eval:
                    sa.groups_id.extend(extract_refs_from_eval(field_eval))

        actions.append(sa)

    return actions


def parse_base_automations_from_xml(filepath: Path) -> List[OdooBaseAutomationRecord]:
    """
    Story S2.3: Parse an Odoo XML file and extract all <record model="base.automation"> declarations.
    Links automation triggers to their associated ir.actions.server records.
    """
    if not filepath.exists():
        _logger.warning("XML file does not exist: %s", filepath)
        return []

    automations: List[OdooBaseAutomationRecord] = []

    try:
        content = filepath.read_text(encoding="utf-8")
        root = ET.fromstring(content)
    except Exception as e:
        _logger.error("Failed to parse XML file %s: %s", filepath, e)
        return []

    for record in root.findall(".//record"):
        model_attr = record.attrib.get("model")
        if model_attr != "base.automation":
            continue

        xml_id = record.attrib.get("id", "")
        ba = OdooBaseAutomationRecord(
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
                ba.name = field_text
            elif field_name == "model_id":
                if field_ref:
                    ba.model_id = field_ref
                elif field_eval:
                    refs = extract_refs_from_eval(field_eval)
                    if refs:
                        ba.model_id = refs[0]
                elif field_text:
                    ba.model_id = field_text
            elif field_name == "trigger":
                ba.trigger = field_text
            elif field_name in {"action_server_ids", "action_server_id"}:
                if field_ref:
                    ba.action_server_ids.append(field_ref)
                if field_eval:
                    ba.action_server_ids.extend(extract_refs_from_eval(field_eval))

        automations.append(ba)

    return automations
