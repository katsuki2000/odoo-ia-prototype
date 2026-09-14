"""
code_intelligence/deterministic/record_rules_models.py

Data structures and evaluation result models for Odoo ir.rule record rules.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Tuple

from code_intelligence.rules.domain import (
    _kleene_and,
    _kleene_or,
    evaluate_domain_force,
)
from core.evidence.evidence import Evidence


@dataclass
class RuleDetail:
    rule_xml_id: str
    rule_name: str
    domain_force: str
    groups: List[str]
    # Bloc P2 Jour 4: Rule node's behavioral_tags/technical_tags copied through
    # so callers can query tags without a second graph lookup.
    tags: List[str] = field(default_factory=list)


@dataclass
class RuleEvaluationResult:
    model_name: str
    user_groups: List[str]
    applied_global_rules: List[RuleDetail] = field(default_factory=list)
    applied_group_rules: List[RuleDetail] = field(default_factory=list)
    ignored_group_rules: List[RuleDetail] = field(default_factory=list)
    effective_domain_summary: str = ""
    summary_text: str = ""
    # B0 pilot: structured Evidence produced at the source, one per rule evaluated.
    evidence: List[Evidence] = field(default_factory=list)

    def can_view_amount(self, amount: float) -> bool:
        """
        Helper method to evaluate effective rules against a specific monetary threshold.
        """
        # Check global rules first (AND logic)
        for rule in self.applied_global_rules:
            m = re.search(r"<=['\"\s]*,['\"\s]*(-?\d+(?:\.\d+)?)", rule.domain_force)
            if m:
                limit = float(m.group(1))
                if amount > limit:
                    return False

        # If user has no applicable group rules, they are NOT restricted by group rules!
        if not self.applied_group_rules:
            return True

        # If user has applied group rules, they are combined with OR
        for rule in self.applied_group_rules:
            dom = rule.domain_force
            if dom in ("[(1, '=', 1)]", "[(1,'=',1)]", "[('id', '!=', False)]"):
                return True
            m = re.search(r"<=['\"\s]*,['\"\s]*(-?\d+(?:\.\d+)?)", dom)
            if m:
                limit = float(m.group(1))
                if amount <= limit:
                    return True
            else:
                # Group rule with no numeric limit allows access
                return True

        return False

    def can_view_amount_v2(self, context: Dict[str, Any]) -> Tuple[Optional[bool], List[str]]:
        """
        Evaluates the full domain_force of every applied rule (global AND group) via
        evaluate_domain_force() using Kleene three-valued logic.

        Returns (verdict, unresolved_fields):
          - verdict: True/False when conclusively resolved, None when uncertain.
          - unresolved_fields: list of field names that could not be determined.
        """
        unresolved: List[str] = []

        # Global rules: AND across ALL of them.
        global_verdict: Optional[bool] = True
        for rule in self.applied_global_rules:
            verdict, rule_unresolved = evaluate_domain_force(rule.domain_force, context)
            global_verdict = _kleene_and(global_verdict, verdict)
            for f in rule_unresolved:
                if f not in unresolved:
                    unresolved.append(f)

        # Group rules: OR across the group rules the user actually belongs to.
        if not self.applied_group_rules:
            group_verdict: Optional[bool] = True
        else:
            group_verdict = False
            for rule in self.applied_group_rules:
                verdict, rule_unresolved = evaluate_domain_force(rule.domain_force, context)
                group_verdict = _kleene_or(group_verdict, verdict)
                for f in rule_unresolved:
                    if f not in unresolved:
                        unresolved.append(f)

        return _kleene_and(global_verdict, group_verdict), unresolved

# ── Record Rules Evaluator ────────────────────────────────────────────────

"""
code_intelligence/deterministic/record_rules.py

Evaluation engine for Odoo ir.rule record rules against user groups and permissions.
"""

from typing import List, Optional
import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.rules.group_resolver import (
    _expand_implied_user_groups,
    _group_fuzzy_matches_display_name,
    _group_short_name,
    resolve_group_identifier,
)
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.utils import format_xml_id_citation
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


def _build_record_rules_evidence(
    model_name: str,
    permission: str,
    user_groups: List[str],
    applied_global: List[RuleDetail],
    applied_group: List[RuleDetail],
    ignored_group: List[RuleDetail],
) -> List[Evidence]:
    """
    B0 pilot: generate one Evidence per rule actually evaluated, at the source.
    """
    scope = {"user_groups": sorted(user_groups)}
    evidence: List[Evidence] = []

    for rule in applied_global:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Global ir.rule '{rule.rule_name}' unconditionally restricts "
                f"{permission} access on '{model_name}' (AND-combined with every other rule)"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    for rule in applied_group:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Group ir.rule '{rule.rule_name}' applies to the requester and "
                f"potentially restricts {permission} access on '{model_name}' "
                f"(OR-combined with other applied group rules)"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    for rule in ignored_group:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Group ir.rule '{rule.rule_name}' exists on '{model_name}' but does NOT "
                f"apply to the requester (not a member of any of its groups: "
                f"{', '.join(rule.groups)})"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    return evidence


def evaluate_record_rules(
    G: nx.DiGraph,
    model_name: str,
    permission: str = "read",
    user_groups: Optional[List[str]] = None
) -> RuleEvaluationResult:
    """
    Stories S2.1 & S2.2: Evaluates Odoo ir.rule record rules for a user, model, and permission type (read, write, create, unlink):
    - Global rules (no groups) are combined with AND across ALL users.
    - Group-specific rules are combined with OR across groups the user belongs to.
    - If user belongs to NO groups linked to a group rule, that group rule is IGNORED (does not restrict the user).
    """
    if user_groups is None:
        user_groups = []

    model_node = f"model:{model_name}"
    perm_attr = f"perm_{permission}" if permission in {"read", "write", "create", "unlink"} else "perm_read"

    if model_node not in G:
        return RuleEvaluationResult(
            model_name=model_name,
            user_groups=user_groups,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER}."
        )

    # Find all rules attached to model that apply to requested permission
    all_rules: List[RuleDetail] = []
    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "RESTRICTED_BY" and G.nodes[neighbor].get("node_type") == "Rule":
            rule_node = G.nodes[neighbor]
            if not rule_node.get(perm_attr, True):
                continue

            rule_groups = []
            for r_neighbor in G.neighbors(neighbor):
                r_edge = G.get_edge_data(neighbor, r_neighbor) or {}
                if r_edge.get("edge_type") == "APPLIES_TO_GROUP":
                    grp_xml_id = r_neighbor.replace("group:", "")
                    rule_groups.append(grp_xml_id)

            all_rules.append(
                RuleDetail(
                    rule_xml_id=rule_node.get("xml_id", neighbor.replace("rule:", "")),
                    rule_name=rule_node.get("name", ""),
                    domain_force=rule_node.get("domain_force", ""),
                    groups=rule_groups,
                    tags=tags_for_node_attrs(rule_node),
                )
            )

    applied_global: List[RuleDetail] = []
    applied_group: List[RuleDetail] = []
    ignored_group: List[RuleDetail] = []

    user_group_set = set(user_groups)
    for g in list(user_group_set):
        _expand_implied_user_groups(G, g, user_group_set)

    def _user_belongs_to_rule_group(user_groups_set: set, rule_groups: List[str]) -> bool:
        """
        Tolerant membership check between user-supplied group identifiers and rule group xml_ids:
          1. Exact match on the full xml_id.
          2. Short-name match.
          3. Fuzzy match against the group's display name.
        """
        if user_groups_set.intersection(rule_groups):
            return True

        short_rule_groups = {_group_short_name(g) for g in rule_groups}
        short_user_groups = {_group_short_name(g) for g in user_groups_set}
        if short_user_groups.intersection(short_rule_groups):
            return True

        for rule_group in rule_groups:
            if resolve_group_identifier(G, next(iter(user_groups_set), ""), [rule_group]) or any(
                _group_fuzzy_matches_display_name(G, ug, rule_group) for ug in user_groups_set
            ):
                return True

        return False

    for rule in all_rules:
        if not rule.groups:
            applied_global.append(rule)
        else:
            if _user_belongs_to_rule_group(user_group_set, rule.groups):
                applied_group.append(rule)
            else:
                ignored_group.append(rule)

    lines = [f"Évaluation des règles d'enregistrement (ir.rule) pour '{model_name}':"]
    if applied_global:
        lines.append("  - Règles Globales (ET pour tous): " + ", ".join([f"{r.rule_name} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in applied_global]))
    else:
        lines.append("  - Règles Globales: Aucune")

    if applied_group:
        lines.append("  - Règles de Groupe applicables (combinées en OU): " + ", ".join([f"{r.rule_name} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in applied_group]))
    else:
        lines.append("  - Règles de Groupe applicables: Aucune (l'utilisateur n'appartient à aucun des groupes visés)")

    if ignored_group:
        lines.append("  - Règles de Groupe ignorées (non-membre): " + ", ".join([f"{r.rule_name} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in ignored_group]))

    if applied_group:
        lines.append(
            "  -> CONCLUSION: Au moins une regle de groupe applicable restreint potentiellement "
            "l'acces -- se referer aux domain_force ci-dessus pour les conditions exactes "
            "(combinees en OU entre elles, puis en ET avec les regles globales)."
        )
    else:
        lines.append(
            "  -> CONCLUSION: Aucune regle de groupe applicable (l'utilisateur n'appartient a aucun "
            "groupe cible par une regle sur ce modele). Seules les regles globales ci-dessus "
            "s'appliquent -- il n'y a AUCUNE restriction supplementaire de montant ou de portee "
            "provenant d'une regle de groupe pour cet utilisateur."
        )

    summary_text = "\n".join(lines)

    evidence = _build_record_rules_evidence(
        model_name, permission, user_groups, applied_global, applied_group, ignored_group
    )

    return RuleEvaluationResult(
        model_name=model_name,
        user_groups=user_groups,
        applied_global_rules=applied_global,
        applied_group_rules=applied_group,
        ignored_group_rules=ignored_group,
        effective_domain_summary=summary_text,
        summary_text=summary_text,
        evidence=evidence,
    )
