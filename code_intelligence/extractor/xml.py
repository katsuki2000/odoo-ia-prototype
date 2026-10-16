"""XML extractors for actions, rules, groups, views, and menus."""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple

from .csv import OdooAccessEntry
from .xml_models import (
    OdooActionRecord,
    OdooBaseAutomationRecord,
    OdooFormButton,
    OdooGroupRecord,
    OdooMailTemplateRecord,
    OdooMenuItemRecord,
    OdooReportRecord,
    OdooRuleRecord,
    OdooServerActionRecord,
    OdooViewRecord,
    OdooXmlFieldRecord,
    extract_refs_from_eval,
    iter_field_attrs,
    iter_records_by_model,
    parse_eval_bool,
    parse_xml_root,
    parse_xml_document,
    _read_and_parse_xml,
)

_logger = logging.getLogger(__name__)

# ── Actions & Automations ──

"""
code_intelligence/extractor/xml_actions.py

XML parsers for ir.actions.act_window, ir.actions.client, ir.actions.server, ir.cron, and base.automation.
"""




_ACTION_TYPES = {"ir.actions.act_window": "act_window", "ir.actions.client": "client"}


def parse_actions_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooActionRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.actions.act_window"> and
    <record model="ir.actions.client"> declarations (a client action has a tag, no res_model).
    """
    if parsed_xml is None:
    root = parse_xml_root(filepath, error_context="for actions")
    else:
        _, root = parsed_xml
    if root is None:
        return []

    actions: List[OdooActionRecord] = []
    for xml_id, record in iter_records_by_model(root, set(_ACTION_TYPES)):
        action = OdooActionRecord(
            xml_id=xml_id,
            filepath=str(filepath),
            lineno=0,
            action_type=_ACTION_TYPES[record.attrib["model"]],
        )

        for field_name, field_text, field_ref, field_eval, _field_elem in iter_field_attrs(record):
            if field_name == "name":
                action.name = field_text
            elif field_name in {"res_model", "model"}:
                action.res_model = field_text or field_ref or ""
            elif field_name == "view_mode":
                action.view_mode = field_text
            elif field_name == "tag":
                action.tag = field_text
            elif field_name == "domain":
                action.domain = field_text or field_eval or ""
            elif field_name in {"groups", "groups_id"}:
                grp_list = []
                if field_ref:
                    grp_list.append(field_ref)
                if field_eval:
                    grp_list.extend(extract_refs_from_eval(field_eval))
                action.groups_id.extend(grp_list)

        actions.append(action)

    return actions


def parse_server_actions_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooServerActionRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.actions.server"> declarations.
    Captures the 'code' field content that contains executable Python logic.
    """
    if parsed_xml is None:
    root = parse_xml_root(filepath, missing_message="XML file does not exist: %s", error_context="")
    else:
        _, root = parsed_xml
    if root is None:
        return []

    actions: List[OdooServerActionRecord] = []

    for xml_id, record in iter_records_by_model(root, {"ir.actions.server", "ir.cron"}):
        model_attr = record.attrib.get("model")
        sa = OdooServerActionRecord(
            xml_id=xml_id,
            filepath=str(filepath),
            lineno=0,
            action_type="cron" if model_attr == "ir.cron" else "server_action",
        )

        for field_name, field_text, field_ref, field_eval, field_elem in iter_field_attrs(record):
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
            elif field_name == "user_id":
                sa.user_id = field_ref or (extract_refs_from_eval(field_eval)[0] if field_eval and extract_refs_from_eval(field_eval) else field_text)
            elif field_name == "interval_number":
                try:
                    sa.interval_number = int(field_text or (field_eval if field_eval else 1))
                except (TypeError, ValueError):
                    _logger.warning("Invalid interval_number %r on server action %s", field_text or field_eval, sa.xml_id)
            elif field_name == "interval_type":
                sa.interval_type = field_text or (field_eval.strip("'\"") if field_eval else "")

        actions.append(sa)

    return actions


def parse_base_automations_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooBaseAutomationRecord]:
    """
    Parse an Odoo XML file and extract all <record model="base.automation"> declarations.
    Links automation triggers to their associated ir.actions.server records.
    """
    root = parse_xml_root(filepath, missing_message="XML file does not exist: %s", error_context="")
    if root is None:
        return []

    automations: List[OdooBaseAutomationRecord] = []

    for xml_id, record in iter_records_by_model(root, "base.automation"):
        ba = OdooBaseAutomationRecord(
            xml_id=xml_id,
            filepath=str(filepath),
            lineno=0,
        )

        for field_name, field_text, field_ref, field_eval, _field_elem in iter_field_attrs(record):
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
# ── Rules & Groups ──

"""
code_intelligence/extractor/xml_rules_groups.py

XML parsers for ir.rule and res.groups declarations.
"""




def parse_ir_rules_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooRuleRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.rule"> declarations.
    """
    if parsed_xml is None:
        result = _read_and_parse_xml(filepath, missing_message="XML file does not exist: %s")
        if result is None:
            return []
        content, root = result
    else:
        content, root = parsed_xml
        if root is None:
            return []
    lines = content.splitlines()

    rules: List[OdooRuleRecord] = []

    for xml_id, record in iter_records_by_model(root, "ir.rule"):
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

        for field_name, field_text, field_ref, field_eval, _field_elem in iter_field_attrs(record):
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


def _record_lineno(lines: List[str], xml_id: str) -> int:
    if xml_id:
        for idx, line in enumerate(lines, 1):
            if f'id="{xml_id}"' in line or f"id='{xml_id}'" in line:
                return idx
    return 1


def _field_refs(field_ref, field_eval) -> List[str]:
    refs: List[str] = []
    if field_ref:
        refs.append(field_ref)
    if field_eval:
        refs.extend(extract_refs_from_eval(field_eval))
    return refs


def parse_reports_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooReportRecord]:
    """Parse an Odoo XML file and extract all <record model="ir.actions.report"> declarations."""
    if parsed_xml is None:
        result = _read_and_parse_xml(filepath, missing_message="XML file does not exist: %s")
        if result is None:
            return []
        content, root = result
    else:
        content, root = parsed_xml
        if root is None:
            return []
    lines = content.splitlines()

    reports: List[OdooReportRecord] = []
    for xml_id, record in iter_records_by_model(root, "ir.actions.report"):
        if not xml_id:
            continue
        report = OdooReportRecord(xml_id=xml_id, filepath=str(filepath), lineno=_record_lineno(lines, xml_id))
        for field_name, field_text, field_ref, field_eval, _ in iter_field_attrs(record):
            if field_name in {"name", "model", "report_type", "report_name", "print_report_name"}:
                setattr(report, field_name, field_text)
            elif field_name == "binding_model_id":
                report.binding_model_id = field_ref or field_text
            elif field_name in {"groups", "groups_id"}:
                report.groups_id.extend(_field_refs(field_ref, field_eval))
        reports.append(report)
    return reports


def parse_mail_templates_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooMailTemplateRecord]:
    """Parse an Odoo XML file and extract all <record model="mail.template"> declarations."""
    if parsed_xml is None:
        result = _read_and_parse_xml(filepath, missing_message="XML file does not exist: %s")
        if result is None:
            return []
        content, root = result
    else:
        content, root = parsed_xml
        if root is None:
            return []
    lines = content.splitlines()

    templates: List[OdooMailTemplateRecord] = []
    for xml_id, record in iter_records_by_model(root, "mail.template"):
        if not xml_id:
            continue
        template = OdooMailTemplateRecord(xml_id=xml_id, filepath=str(filepath), lineno=_record_lineno(lines, xml_id))
        for field_name, field_text, field_ref, field_eval, _ in iter_field_attrs(record):
            if field_name in {"name", "subject", "description", "email_from", "email_to", "partner_to", "lang"}:
                setattr(template, field_name, field_text)
            elif field_name == "model_id":
                template.model_id = field_ref or field_text
            elif field_name == "report_template_ids":
                template.report_template_ids.extend(_field_refs(field_ref, field_eval))
            elif field_name == "active":
                template.active = parse_eval_bool(field_eval, field_text, default=True)
        templates.append(template)
    return templates


def parse_access_entries_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooAccessEntry]:
    """
    Parse an Odoo XML file and extract all <record model="ir.model.access"> declarations.

    Same semantics as the CSV extractor: missing permissions default to False and a
    missing group means the entry applies to every authenticated user.
    """
    if parsed_xml is None:
        result = _read_and_parse_xml(filepath, missing_message="XML file does not exist: %s")
        if result is None:
            return []
        content, root = result
    else:
        content, root = parsed_xml
        if root is None:
            return []
    lines = content.splitlines()

    entries: List[OdooAccessEntry] = []

    for xml_id, record in iter_records_by_model(root, "ir.model.access"):
        if not xml_id:
            continue
        lineno = 1
        for idx, line in enumerate(lines, 1):
            if f'id="{xml_id}"' in line or f"id='{xml_id}'" in line:
                lineno = idx
                break

        entry = OdooAccessEntry(xml_id=xml_id, filepath=str(filepath), lineno=lineno)
        for field_name, field_text, field_ref, field_eval, _ in iter_field_attrs(record):
            if field_name == "name":
                entry.name = field_text
            elif field_name == "model_id":
                entry.model_id = field_ref or field_text
            elif field_name == "group_id":
                group = field_ref
                if not group and field_eval:
                    refs = extract_refs_from_eval(field_eval)
                    group = refs[0] if refs else None
                entry.group_id = group or field_text or None
            elif field_name in {"perm_read", "perm_write", "perm_create", "perm_unlink"}:
                setattr(entry, field_name, parse_eval_bool(field_eval, field_text, default=False))
        entry.all_authenticated = not entry.group_id
        entries.append(entry)

    return entries


def parse_groups_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooGroupRecord]:
    """
    Parse an Odoo XML file and extract all <record model="res.groups"> declarations.
    """
    if parsed_xml is None:
    root = parse_xml_root(filepath, error_context="for groups")
    else:
        _, root = parsed_xml
    if root is None:
        return []

    groups: List[OdooGroupRecord] = []

    for xml_id, record in iter_records_by_model(root, "res.groups"):
        group = OdooGroupRecord(
            xml_id=xml_id,
            filepath=str(filepath),
            lineno=0,
        )

        for field_name, field_text, field_ref, field_eval, _field_elem in iter_field_attrs(record):
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
# ── Views & Menus ──

"""
code_intelligence/extractor/xml_views.py

XML parsers for views, form buttons, menuitems, and ir.model.fields declarations.
"""




def parse_xml_fields_from_xml(filepath: Path) -> List[OdooXmlFieldRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.model.fields"> declarations.
    """
    root = parse_xml_root(filepath, error_context="for xml fields")
    if root is None:
        return []

    fields_list: List[OdooXmlFieldRecord] = []

    for xml_id, record in iter_records_by_model(root, "ir.model.fields"):
        f_rec = OdooXmlFieldRecord(xml_id=xml_id, filepath=str(filepath), lineno=0)

        for field_name, field_text, field_ref, _field_eval, _field_elem in iter_field_attrs(record):
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


def parse_menuitems_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooMenuItemRecord]:
    """
    Parse an Odoo XML file and extract all <menuitem> elements and <record model="ir.ui.menu"> records.
    """
    if parsed_xml is None:
    root = parse_xml_root(filepath, error_context="for menuitems")
    else:
        _, root = parsed_xml
    if root is None:
        return []

    menuitems: List[OdooMenuItemRecord] = []

    # Section 1199: Odoo takes the enclosing <menuitem> as parent when the
    # `parent` attribute is absent (nested menus, e.g. account_menuitem.xml).
    enclosing_of = {child: node for node in root.iter() for child in node}

    # 1. Concise <menuitem .../> elements
    for elem in root.findall(".//menuitem"):
        xml_id = elem.attrib.get("id", "")
        name = elem.attrib.get("name", "")
        parent = elem.attrib.get("parent", "")
        if not parent:
            enclosing = enclosing_of.get(elem)
            if enclosing is not None and enclosing.tag == "menuitem":
                parent = enclosing.attrib.get("id", "")
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
    for xml_id, record in iter_records_by_model(root, "ir.ui.menu"):
        menu = OdooMenuItemRecord(xml_id=xml_id, filepath=str(filepath), lineno=0)

        for field_name, field_text, field_ref, field_eval, _field_elem in iter_field_attrs(record):
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


def parse_views_from_xml(filepath: Path, *, parsed_xml: Optional[Tuple[str, Optional[ET.Element]]] = None) -> List[OdooViewRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.ui.view"> records with form buttons.
    """
    if parsed_xml is None:
    root = parse_xml_root(filepath, error_context="for views")
    else:
        _, root = parsed_xml
    if root is None:
        return []

    views: List[OdooViewRecord] = []

    for xml_id, record in iter_records_by_model(root, "ir.ui.view"):
        view = OdooViewRecord(xml_id=xml_id, filepath=str(filepath), lineno=0)

        for field_name, field_text, field_ref, _field_eval, field_elem in iter_field_attrs(record):
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
