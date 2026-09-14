"""
code_intelligence/deterministic/access_evaluator.py

Evaluation of model-level Access Control Lists (ACLs, ir.model.access)
and combining with ir.rule record rules.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.rules.group_resolver import (
    _expand_inheriting_acl_groups,
    resolve_group_identifier,
)
from code_intelligence.rules.record_rules import RuleDetail
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.utils import format_xml_id_citation, format_xml_id_citations
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


@dataclass
class AccessEvaluationResult:
    model_name: str
    requested_permission: str
    allowed_groups: List[str] = field(default_factory=list)
    all_authenticated_access: bool = False
    active_rules: List[RuleDetail] = field(default_factory=list)
    client_side_checks: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot: structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)


def _build_access_evidence(
    model_name: str,
    permission: str,
    allowed_groups: Set[str],
    all_authenticated: bool,
    active_rules: List[RuleDetail],
    group_id: Optional[str] = None,
) -> List[Evidence]:
    """
    B1: one Evidence for the ACL grant fact, plus one Evidence per active ir.rule found.
    """
    scope: Dict[str, Any] = {"group_id": group_id} if group_id else {}
    evidence: List[Evidence] = []

    if all_authenticated:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"ACL grants {permission} access on '{model_name}' to all authenticated users",
            source=f"acl:{model_name}:{permission}",
            value=True,
            confidence="HIGH",
            scope=scope,
        ))
    elif allowed_groups:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"ACL grants {permission} access on '{model_name}' to groups: {', '.join(sorted(allowed_groups))}",
            source=f"acl:{model_name}:{permission}",
            value=sorted(allowed_groups),
            confidence="HIGH",
            scope=scope,
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"No ACL explicitly grants {permission} access on '{model_name}'",
            source=f"acl:{model_name}:{permission}",
            value=None,
            confidence="HIGH",
            scope=scope,
        ))

    for rule in active_rules:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"ir.rule '{rule.rule_name}' can further restrict {permission} access "
                f"on '{model_name}' (groups: {', '.join(rule.groups) if rule.groups else 'global, applies to all'})"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    return evidence


def _eval_single_permission(G: nx.DiGraph, model_name: str, permission: str, group_id: Optional[str] = None):
    model_node = f"model:{model_name}"
    perm_attr = f"perm_{permission}" if permission in {"read", "write", "create", "unlink"} else "perm_read"

    if model_node not in G:
        return set(), False, []

    allowed_groups: Set[str] = set()
    all_authenticated = False
    active_rules: List[RuleDetail] = []

    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        edge_type = edge_data.get("edge_type")

        if edge_type == "GRANTED_BY" and G.nodes[neighbor].get("node_type") == "AccessEntry":
            acl_node = G.nodes[neighbor]
            if acl_node.get(perm_attr, False):
                if acl_node.get("all_authenticated", False):
                    all_authenticated = True

                for acl_neighbor in G.neighbors(neighbor):
                    acl_edge = G.get_edge_data(neighbor, acl_neighbor) or {}
                    if acl_edge.get("edge_type") == "APPLIES_TO_GROUP":
                        grp_xml_id = acl_neighbor.replace("group:", "")
                        allowed_groups.add(grp_xml_id)
                        _expand_inheriting_acl_groups(G, grp_xml_id, allowed_groups)

        elif edge_type == "RESTRICTED_BY" and G.nodes[neighbor].get("node_type") == "Rule":
            rule_node = G.nodes[neighbor]
            if rule_node.get(perm_attr, True):
                rule_groups = []
                for rule_neighbor in G.neighbors(neighbor):
                    rule_edge = G.get_edge_data(neighbor, rule_neighbor) or {}
                    if rule_edge.get("edge_type") == "APPLIES_TO_GROUP":
                        grp_xml_id = rule_neighbor.replace("group:", "")
                        rule_groups.append(grp_xml_id)

                active_rules.append(
                    RuleDetail(
                        rule_xml_id=rule_node.get("xml_id", neighbor.replace("rule:", "")),
                        rule_name=rule_node.get("name", ""),
                        domain_force=rule_node.get("domain_force", ""),
                        groups=rule_groups,
                        tags=tags_for_node_attrs(rule_node),
                    )
                )

    return allowed_groups, all_authenticated, active_rules


def who_has_access_to(
    G: nx.DiGraph,
    model_name: str,
    permission: str = "read",
    group_id: Optional[str] = None
) -> AccessEvaluationResult:
    """
    Evaluates access rights for a given model and permission type.
    Combines CSV ACLs, ir.rule domain_force expressions, res.groups implied hierarchy, and JS client checks.
    Supports permission='all' to evaluate all 4 permissions in a single pass.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return AccessEvaluationResult(
            model_name=model_name,
            requested_permission=permission,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
        )

    if permission.lower() == "all":
        rights_summary = []
        all_allowed: Set[str] = set()
        all_rules: List[RuleDetail] = []
        all_auth = False
        all_evidence: List[Evidence] = []

        for p in ["read", "write", "create", "unlink"]:
            grps, auth, rules = _eval_single_permission(G, model_name, p, group_id)
            all_allowed.update(grps)
            all_rules.extend(rules)
            if auth:
                all_auth = True
            all_evidence.extend(_build_access_evidence(model_name, p, grps, auth, rules, group_id))

            grp_str = "All authenticated users" if auth else (", ".join(sorted(grps)) if grps else "None")
            _grp_citations = format_xml_id_citations(sorted(grps)) if (grps and not auth) else ""
            _grp_suffix = f" ({_grp_citations})" if _grp_citations else ""
            rights_summary.append(f"[{p.upper()}]: {grp_str} (Rules: {len(rules)}){_grp_suffix}")

        summary = f"Access Matrix for '{model_name}':\n" + "\n".join(rights_summary)

        return AccessEvaluationResult(
            model_name=model_name,
            requested_permission="all",
            allowed_groups=sorted(list(all_allowed)),
            all_authenticated_access=all_auth,
            active_rules=all_rules,
            summary_text=summary,
            evidence=all_evidence,
        )

    # Single permission evaluation
    allowed_groups, all_authenticated, active_rules = _eval_single_permission(G, model_name, permission, group_id)

    if group_id:
        resolved_group_id = resolve_group_identifier(G, group_id, list(allowed_groups)) if allowed_groups else None
        if resolved_group_id is None and not all_authenticated:
            summary = (
                f"Group identifier '{group_id}' could not be resolved against any group "
                f"with {permission.upper()} rules or ACLs on '{model_name}'. This does NOT mean "
                f"access is denied -- it means the identifier itself could not be matched. "
                f"Try list_involved_modules or resolve_technical_name to find the exact group xml_id."
            )
        else:
            has_access = all_authenticated or (resolved_group_id is not None)
            display_id = resolved_group_id or group_id
            _display_citation = format_xml_id_citation(display_id)
            summary = (
                f"Group '{display_id}' HAS {permission.upper()} access to '{model_name}'. ({_display_citation})"
                if has_access
                else f"Group '{display_id}' DOES NOT HAVE {permission.upper()} access to '{model_name}'. ({_display_citation})"
            )
    else:
        if all_authenticated:
            grp_str = "All authenticated users"
        elif allowed_groups:
            grp_str = ", ".join(sorted(allowed_groups))
        else:
            grp_str = "No groups explicitly granted"

        _allowed_citations = (
            format_xml_id_citations(sorted(allowed_groups))
            if (allowed_groups and not all_authenticated) else ""
        )
        _allowed_suffix = f" ({_allowed_citations})" if _allowed_citations else ""
        summary = f"Model '{model_name}' [{permission.upper()}]: Granted to {grp_str}.{_allowed_suffix} Active Rules: {len(active_rules)}."

    return AccessEvaluationResult(
        model_name=model_name,
        requested_permission=permission,
        allowed_groups=sorted(list(allowed_groups)),
        all_authenticated_access=all_authenticated,
        active_rules=active_rules,
        client_side_checks=[],
        summary_text=summary,
        evidence=_build_access_evidence(model_name, permission, allowed_groups, all_authenticated, active_rules, group_id),
    )
