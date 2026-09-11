"""
code_intelligence/extractor/xml_actions.py

XML parsers for ir.actions.act_window, ir.actions.server, ir.cron, and base.automation.
"""

from pathlib import Path
from typing import List

from .xml_models import (
    OdooActionRecord,
    OdooBaseAutomationRecord,
    OdooServerActionRecord,
    extract_refs_from_eval,
    iter_field_attrs,
    iter_records_by_model,
    parse_xml_root,
)


def parse_actions_from_xml(filepath: Path) -> List[OdooActionRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.actions.act_window"> declarations.
    """
    root = parse_xml_root(filepath, error_context="for actions")
    if root is None:
        return []

    actions: List[OdooActionRecord] = []
    for xml_id, record in iter_records_by_model(root, "ir.actions.act_window"):
        action = OdooActionRecord(
            xml_id=xml_id,
            filepath=str(filepath),
            lineno=0,
        )

        for field_name, field_text, field_ref, field_eval, _field_elem in iter_field_attrs(record):
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


def parse_server_actions_from_xml(filepath: Path) -> List[OdooServerActionRecord]:
    """
    Parse an Odoo XML file and extract all <record model="ir.actions.server"> declarations.
    Captures the 'code' field content that contains executable Python logic.
    """
    root = parse_xml_root(filepath, missing_message="XML file does not exist: %s", error_context="")
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
                except Exception:
                    pass
            elif field_name == "interval_type":
                sa.interval_type = field_text or (field_eval.strip("'\"") if field_eval else "")

        actions.append(sa)

    return actions


def parse_base_automations_from_xml(filepath: Path) -> List[OdooBaseAutomationRecord]:
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
