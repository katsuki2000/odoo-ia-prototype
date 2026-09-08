"""
code_intelligence/graph/symbol_merger.py

Merge helpers for XML records extended across modules in Odoo load order.
"""

from code_intelligence.extractor.xml_extractor import (
    OdooActionRecord,
    OdooGroupRecord,
    OdooRuleRecord,
    OdooServerActionRecord,
)


def _merge_action(existing: OdooActionRecord, new: OdooActionRecord) -> OdooActionRecord:
    """
    Merge an extension record (e.g. <record id="base.action_partner_form">
    re-declared in a dependent module to tweak view_mode/domain/context)
    onto the originally-declared action, instead of overwriting it wholesale.
    Odoo's own record-inheritance semantics only replace the fields the
    extension explicitly sets; fields it omits keep their inherited value.
    """
    new.res_model = new.res_model or existing.res_model
    new.view_mode = new.view_mode or existing.view_mode
    new.name = new.name or existing.name
    new.groups_id = new.groups_id or existing.groups_id
    return new


def _merge_server_action(existing: OdooServerActionRecord, new: OdooServerActionRecord) -> OdooServerActionRecord:
    new.model_id = getattr(new, "model_id", "") or getattr(existing, "model_id", "")
    new.name = getattr(new, "name", "") or getattr(existing, "name", "")
    return new


def _merge_rule(existing: OdooRuleRecord, new: OdooRuleRecord) -> OdooRuleRecord:
    new.model_id = getattr(new, "model_id", "") or getattr(existing, "model_id", "")
    new.domain_force = getattr(new, "domain_force", "") or getattr(existing, "domain_force", "")
    new.groups_id = getattr(new, "groups_id", None) or getattr(existing, "groups_id", [])
    return new


def _merge_group(existing: OdooGroupRecord, new: OdooGroupRecord) -> OdooGroupRecord:
    new.implied_ids = getattr(new, "implied_ids", None) or getattr(existing, "implied_ids", [])
    new.name = getattr(new, "name", "") or getattr(existing, "name", "")
    return new


__all__ = [
    "_merge_action",
    "_merge_server_action",
    "_merge_rule",
    "_merge_group",
]
