"""
live-vs-deterministic validator for Odoo ACL and ir.rule behavior.

This module deliberately compares the deterministic graph prediction against
Odoo's own XML-RPC behavior. It does not attempt to replace Odoo's security
engine; it reports mismatches with enough record ids and rule names for review.
"""

from __future__ import annotations

import xmlrpc.client
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import networkx as nx

from code_intelligence.deterministic_tools import (
    evaluate_record_rules,
    who_has_access_to,
    resolve_group_identifier,
)
from code_intelligence.odoo_rpc_client import OdooRpcClient


@dataclass
class LiveRuleReference:
    model: str
    record_id: int
    xml_id: str
    name: str
    domain_force: str = ""


@dataclass
class LiveRuleValidationResult:
    user_login: str
    uid: int
    model_name: str
    operation: str
    domain: List[Any]
    user_group_xml_ids: List[str] = field(default_factory=list)
    deterministic_acl_allowed: bool = False
    deterministic_record_rule_allowed: Optional[bool] = None
    deterministic_allowed: bool = False
    live_allowed: bool = False
    live_record_ids: List[int] = field(default_factory=list)
    live_fault: str = ""
    live_rule_refs: List[LiveRuleReference] = field(default_factory=list)
    has_divergence: bool = False
    summary_text: str = ""


def validate_live_rule_prediction(
    client: OdooRpcClient,
    G: nx.DiGraph,
    user_login: str,
    password: str,
    model_name: str,
    domain: List[Any],
    operation: str = "read",
    amount: Optional[float] = None,
    admin_uid: Optional[int] = None,
) -> LiveRuleValidationResult:
    """
    Compare deterministic ACL/rule evaluation with Odoo live XML-RPC search.

    The deterministic side rejects immediately when ACLs deny the operation,
    matching Odoo's ACL-before-ir.rule behavior. When ACLs allow, record-rule
    prediction is evaluated from graph rules using the supplied domain amount
    when possible.
    """
    uid = client.authenticate_user(user_login, password)
    admin = admin_uid if admin_uid is not None else client.authenticate_admin()
    user_group_xml_ids = _user_group_xml_ids(client, admin, uid)

    deterministic_acl_allowed = _deterministic_acl_allows(
        G,
        model_name,
        operation,
        user_group_xml_ids,
    )

    deterministic_record_rule_allowed: Optional[bool] = None
    if deterministic_acl_allowed:
        rule_eval = evaluate_record_rules(
            G,
            model_name,
            permission=operation,
            user_groups=user_group_xml_ids,
        )
        resolved_amount = amount if amount is not None else _amount_from_domain(domain)
        deterministic_record_rule_allowed = (
            rule_eval.can_view_amount(resolved_amount)
            if resolved_amount is not None
            else True
        )

    deterministic_allowed = deterministic_acl_allowed and (
        deterministic_record_rule_allowed is not False
    )

    live_record_ids: List[int] = []
    live_fault = ""
    try:
        live_record_ids = client.search_as_user(
            uid,
            model_name,
            domain,
            operation=operation,
            limit=20,
        )
        live_allowed = bool(live_record_ids)
    except xmlrpc.client.Fault as exc:
        live_allowed = False
        live_fault = exc.faultString

    live_rule_refs = _live_rule_refs(client, admin, model_name, operation)
    has_divergence = deterministic_allowed != live_allowed
    summary_text = _format_summary(
        user_login=user_login,
        model_name=model_name,
        operation=operation,
        deterministic_acl_allowed=deterministic_acl_allowed,
        deterministic_record_rule_allowed=deterministic_record_rule_allowed,
        deterministic_allowed=deterministic_allowed,
        live_allowed=live_allowed,
        live_record_ids=live_record_ids,
        live_fault=live_fault,
        live_rule_refs=live_rule_refs,
        has_divergence=has_divergence,
    )

    return LiveRuleValidationResult(
        user_login=user_login,
        uid=uid,
        model_name=model_name,
        operation=operation,
        domain=domain,
        user_group_xml_ids=user_group_xml_ids,
        deterministic_acl_allowed=deterministic_acl_allowed,
        deterministic_record_rule_allowed=deterministic_record_rule_allowed,
        deterministic_allowed=deterministic_allowed,
        live_allowed=live_allowed,
        live_record_ids=live_record_ids,
        live_fault=live_fault,
        live_rule_refs=live_rule_refs,
        has_divergence=has_divergence,
        summary_text=summary_text,
    )


def _deterministic_acl_allows(
    G: nx.DiGraph,
    model_name: str,
    operation: str,
    user_group_xml_ids: List[str],
) -> bool:
    acl_eval = who_has_access_to(G, model_name, permission=operation)
    if acl_eval.all_authenticated_access:
        return True
    if not acl_eval.allowed_groups:
        return False
    for user_group in user_group_xml_ids:
        if resolve_group_identifier(G, user_group, acl_eval.allowed_groups):
            return True
    return False


def _user_group_xml_ids(client: OdooRpcClient, admin_uid: int, uid: int) -> List[str]:
    users = client.execute_kw(
        admin_uid,
        "res.users",
        "read",
        [[uid]],
        {"fields": ["groups_id"]},
    )
    group_ids = users[0].get("groups_id", []) if users else []
    xml_by_id = _external_ids_by_record_id(client, admin_uid, "res.groups", group_ids)
    return sorted(xml_by_id.values())


def _live_rule_refs(
    client: OdooRpcClient,
    admin_uid: int,
    model_name: str,
    operation: str,
) -> List[LiveRuleReference]:
    perm_field = f"perm_{operation}"
    rules = client.execute_kw(
        admin_uid,
        "ir.rule",
        "search_read",
        [[("model_id.model", "=", model_name), ("active", "=", True), (perm_field, "=", True)]],
        {"fields": ["id", "name", "domain_force"]},
    )
    xml_by_id = _external_ids_by_record_id(
        client,
        admin_uid,
        "ir.rule",
        [rule["id"] for rule in rules],
    )
    return [
        LiveRuleReference(
            model="ir.rule",
            record_id=rule["id"],
            xml_id=xml_by_id.get(rule["id"], ""),
            name=rule.get("name", ""),
            domain_force=rule.get("domain_force", ""),
        )
        for rule in rules
    ]


def _external_ids_by_record_id(
    client: OdooRpcClient,
    admin_uid: int,
    model: str,
    record_ids: List[int],
) -> Dict[int, str]:
    if not record_ids:
        return {}
    rows = client.execute_kw(
        admin_uid,
        "ir.model.data",
        "search_read",
        [[("model", "=", model), ("res_id", "in", record_ids)]],
        {"fields": ["module", "name", "res_id"]},
    )
    return {
        int(row["res_id"]): f"{row['module']}.{row['name']}"
        for row in rows
        if row.get("module") and row.get("name") and row.get("res_id")
    }


def _amount_from_domain(domain: List[Any]) -> Optional[float]:
    for term in domain:
        if (
            isinstance(term, (list, tuple))
            and len(term) == 3
            and term[0] == "amount_total"
            and term[1] in {">", ">=", "=", "<=", "<"}
        ):
            try:
                return float(term[2])
            except (TypeError, ValueError):
                return None
    return None


def _format_summary(
    user_login: str,
    model_name: str,
    operation: str,
    deterministic_acl_allowed: bool,
    deterministic_record_rule_allowed: Optional[bool],
    deterministic_allowed: bool,
    live_allowed: bool,
    live_record_ids: List[int],
    live_fault: str,
    live_rule_refs: List[LiveRuleReference],
    has_divergence: bool,
) -> str:
    rule_refs = ", ".join(
        f"{ref.xml_id or 'no_xml_id'}#{ref.record_id}:{ref.name}" for ref in live_rule_refs
    )
    return (
        f"live validation for {user_login} on {model_name}/{operation}: "
        f"deterministic_acl={deterministic_acl_allowed}, "
        f"deterministic_ir_rule={deterministic_record_rule_allowed}, "
        f"deterministic_allowed={deterministic_allowed}, "
        f"live_allowed={live_allowed}, live_record_ids={live_record_ids}, "
        f"divergence={has_divergence}. "
        f"Live ir.rule refs: {rule_refs or 'none'}. "
        f"Live fault: {live_fault[:240] if live_fault else 'none'}"
    )
