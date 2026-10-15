"""
code_intelligence/live/comparator.py

Live Odoo Database Comparator for Odoo Code Intelligence.
Compares static security graph declarations against live database rules via XML-RPC.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
import logging

from code_intelligence.graph import ResolvedSymbolRegistry

_logger = logging.getLogger(__name__)


@dataclass
class DivergenceDetail:
    divergence_type: str # "GROUP_ADDED_IN_LIVE", "DOMAIN_MODIFIED", "RULE_DISABLED_IN_LIVE"
    symbol_name: str
    static_value: str
    live_value: str
    explanation: str


@dataclass
class DivergenceComparisonResult:
    model_name: str
    has_divergence: bool
    divergences: List[DivergenceDetail] = field(default_factory=list)
    summary_text: str = ""


# TTL Cache storage
_LIVE_CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 300.0 # 5 minutes


def clear_live_cache():
    """Manual cache invalidation for A4.1.2."""
    global _LIVE_CACHE
    _LIVE_CACHE.clear()
    _logger.info("Cleared Live XML-RPC TTL cache.")


def fetch_live_model_security(model_name: str, odoo_client: Optional[Any] = None) -> Dict[str, Any]:
    """
    Fetch live security rules and ACLs from Odoo database via XML-RPC.
    Uses 5-minute TTL cache (A4.1.2).
    """
    cache_key = f"live_sec:{model_name}"
    now = time.time()

    if cache_key in _LIVE_CACHE:
        ts, cached_data = _LIVE_CACHE[cache_key]
        if now - ts < CACHE_TTL_SECONDS:
            _logger.info("Returned live security for '%s' from TTL cache.", model_name)
            return cached_data

    # Perform live fetching if client available or simulate
    live_data: Dict[str, Any] = {"rules": [], "acls": []}

    if odoo_client:
        try:
            # Query ir.rule for model
            rule_ids = odoo_client.search("ir.rule", [("model_id.model", "=", model_name)])
            rules = odoo_client.read("ir.rule", rule_ids, ["name", "domain_force", "active", "groups"])
            live_data["rules"] = rules

            # Query ir.model.access for model
            acl_ids = odoo_client.search("ir.model.access", [("model_id.model", "=", model_name)])
            acls = odoo_client.read("ir.model.access", acl_ids, ["name", "group_id", "perm_read", "perm_write", "perm_create", "perm_unlink"])
            live_data["acls"] = acls

        except Exception as e:
            _logger.error("XML-RPC call failed for model %s: %s", model_name, e)

    _LIVE_CACHE[cache_key] = (now, live_data)
    return live_data


def compare_static_vs_live_rules(
    registry: ResolvedSymbolRegistry,
    model_name: str,
    live_data: Dict[str, Any]
) -> DivergenceComparisonResult:
    """
    Compares static code security graph against live database rules.
    Detects divergence types: GROUP_ADDED_IN_LIVE, DOMAIN_MODIFIED, RULE_DISABLED_IN_LIVE.
    """
    divergences: List[DivergenceDetail] = []

    clean_model_target = model_name.replace(".", "_")
    static_rules = [
        r for r in registry.rules.values()
        if r.model_id and clean_model_target in r.model_id.replace(".", "_")
    ]
    live_rules = live_data.get("rules", [])

    # 1. Compare Rules
    for l_rule in live_rules:
        l_name = l_rule.get("name", "")
        l_domain = l_rule.get("domain_force", "")
        l_active = l_rule.get("active", True)

        # Check if disabled in live
        if not l_active:
            divergences.append(
                DivergenceDetail(
                    divergence_type="RULE_DISABLED_IN_LIVE",
                    symbol_name=l_name,
                    static_value="active: True (XML)",
                    live_value="active: False (DB)",
                    explanation=f"Rule '{l_name}' is active in static XML but disabled (active=False) in live database."
                )
            )

        # Find matching static rule
        matching_static = None
        for s_rule in static_rules:
            if s_rule.name == l_name or s_rule.xml_id in l_name:
                matching_static = s_rule
                break

        if matching_static:
            # Check domain force modification
            if matching_static.domain_force.strip() != l_domain.strip():
                divergences.append(
                    DivergenceDetail(
                        divergence_type="DOMAIN_MODIFIED",
                        symbol_name=l_name,
                        static_value=matching_static.domain_force,
                        live_value=l_domain,
                        explanation=f"Domain for rule '{l_name}' was modified in database: Static='{matching_static.domain_force}' vs Live='{l_domain}'."
                    )
                )
        else:
            # Rule created in live DB
            divergences.append(
                DivergenceDetail(
                    divergence_type="GROUP_ADDED_IN_LIVE",
                    symbol_name=l_name,
                    static_value="Not in Code",
                    live_value=f"Domain: {l_domain}",
                    explanation=f"Rule '{l_name}' exists in live database but is absent from static source code."
                )
            )

    has_divergence = len(divergences) > 0
    summary = (
        f"Divergence Analysis for '{model_name}': {len(divergences)} divergences detected."
        if has_divergence
        else f"Divergence Analysis for '{model_name}': Static code and live database are 100% in sync."
    )

    return DivergenceComparisonResult(
        model_name=model_name,
        has_divergence=has_divergence,
        divergences=divergences,
        summary_text=summary,
    )

# ── Validator ───────────────────────────────────────────────────────────

"""
live-vs-deterministic validator for Odoo ACL and ir.rule behavior.

This module deliberately compares the deterministic graph prediction against
Odoo's own XML-RPC behavior. It does not attempt to replace Odoo's security
engine; it reports mismatches with enough record ids and rule names for review.
"""


import xmlrpc.client
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import networkx as nx

from code_intelligence.rules.record_rules import evaluate_record_rules
from code_intelligence.rules.access_evaluator import who_has_access_to
from code_intelligence.rules.group_resolver import resolve_group_identifier
from .rpc_client import OdooRpcClient


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
