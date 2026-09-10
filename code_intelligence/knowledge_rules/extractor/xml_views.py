"""
code_intelligence/extractor/xml_views.py

XML parsers for views, form buttons, menuitems, and ir.model.fields declarations.
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from .xml_models import (
    OdooFormButton,
    OdooMenuItemRecord,
    OdooViewRecord,
    OdooXmlFieldRecord,
    extract_refs_from_eval,
)

_logger = logging.getLogger(__name__)


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
                    invisible=btn_invisible,
                )
            )
    return buttons


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
