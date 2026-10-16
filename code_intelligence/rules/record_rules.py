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

from code_intelligence.rules.model_suggestions import model_not_found_message
from code_intelligence.rules.group_resolver import (
    _expand_implied_user_groups,
    get_group_display_name,
    resolve_group_identifier,
)
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.rules.relevance_budget import assemble_relevance_ranked_blocks
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
    model_node = f"model:{model_name}"
    perm_attr = f"perm_{permission}" if permission in {"read", "write", "create", "unlink"} else "perm_read"

    if model_node not in G:
        return RuleEvaluationResult(
            model_name=model_name,
            user_groups=user_groups or [],
            summary_text=model_not_found_message(G, model_name)
        )

    if user_groups is None:
        message = (
            f"Cannot evaluate record rules for '{model_name}': requester group "
            "membership is unresolved. No conclusion about group restrictions "
            "or effective access can be made."
        )
        return RuleEvaluationResult(
            model_name=model_name,
            user_groups=[],
            effective_domain_summary=message,
            summary_text=message,
            evidence=[],
        )

    # Find all rules attached to model that apply to requested permission
    all_rules: List[RuleDetail] = []
    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "RESTRICTED_BY" and G.nodes[neighbor].get("node_type") == "Rule":
            rule_node = G.nodes[neighbor]
            # Inactive rules (active=0) are kept in the graph but never enforced.
            if not rule_node.get("active", True) or not rule_node.get(perm_attr, True):
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

    requested_groups = set(user_groups)
    user_group_set = set(requested_groups)
    for g in requested_groups:
        _expand_implied_user_groups(G, g, user_group_set)

    def _user_belongs_to_rule_group(rule_groups: List[str]) -> bool:
        """
        Implied groups are canonical xml_ids, so they only match exactly.
        The tolerant resolver (short name, display-name fuzzy match) is meant
        for imprecise identifiers and applies to the requested groups alone.
        """
        if user_group_set.intersection(rule_groups):
            return True
        return any(resolve_group_identifier(G, ug, rule_groups) for ug in requested_groups)

    for rule in all_rules:
        if not rule.groups:
            applied_global.append(rule)
        else:
            if _user_belongs_to_rule_group(rule.groups):
                applied_group.append(rule)
            else:
                ignored_group.append(rule)

    header_text = f"Évaluation des règles d'enregistrement (ir.rule) pour '{model_name}':"
    body_blocks: List[str] = []
    if applied_global:
        body_blocks.append("  - Règles Globales (ET pour tous): " + ", ".join([f"{r.rule_name} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in applied_global]))
    else:
        body_blocks.append("  - Règles Globales: Aucune")

    def _format_rule_groups(rule: RuleDetail) -> str:
        if not rule.groups:
            return ""
        formatted = []
        for g in sorted(rule.groups):
            dname = get_group_display_name(G, g)
            formatted.append(f"{g} ('{dname}')" if dname else g)
        return f" (groupes: {', '.join(formatted)})"

    if applied_group:
        body_blocks.append("  - Règles de Groupe applicables (combinées en OU): " + ", ".join([f"{r.rule_name}{_format_rule_groups(r)} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in applied_group]))
    else:
        body_blocks.append("  - Règles de Groupe applicables: Aucune (l'utilisateur n'appartient à aucun des groupes visés)")

    if ignored_group:
        body_blocks.append("  - Règles de Groupe ignorées (non-membre): " + ", ".join([f"{r.rule_name}{_format_rule_groups(r)} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in ignored_group]))

    if applied_group:
        body_blocks.append(
            "  -> CONCLUSION: Au moins une regle de groupe applicable restreint potentiellement "
            "l'acces -- se referer aux domain_force ci-dessus pour les conditions exactes "
            "(combinees en OU entre elles, puis en ET avec les regles globales)."
        )
    else:
        if user_group_set:
            formatted_ug = []
            for ug in sorted(user_group_set):
                dname = get_group_display_name(G, ug)
                formatted_ug.append(f"{ug} ('{dname}')" if dname else ug)
            evaluated_groups_desc = f"l'ensemble de groupes evalue ({', '.join(formatted_ug)})"
        else:
            evaluated_groups_desc = "un utilisateur n'appartenant a aucun groupe"
        body_blocks.append(
            "  -> CONCLUSION: Aucune regle de groupe applicable (l'utilisateur n'appartient a aucun "
            "groupe cible par une regle sur ce modele). Seules les regles globales ci-dessus "
            f"s'appliquent -- il n'y a aucune restriction supplementaire de montant ou de portee "
            f"provenant d'une regle de groupe pour {evaluated_groups_desc}. Ce constat NE S'ETEND A "
            "AUCUNE AUTRE PERSONA eventuellement mentionnee dans la question -- il ne vaut que pour "
            "l'ensemble de groupes precis evalue ici."
        )

    # Section 950 (todo/contexte.txt section 948, point 1): these 4 blocks
    # used to be flat-joined and left to the generic, position-blind
    # head-truncation in context.py::_truncate_observation, which -- once
    # a verbose "ignorées" block (the LEAST essential one, listing rules
    # that do not even apply to the requester) pushes past the cap --
    # drops it AND every block after it, including the CONCLUSION and the
    # actually-applicable group rules whenever they happen to be assembled
    # last in a long turn (cumulative budget squeeze, section 947 point 1).
    # assemble_relevance_ranked_blocks keeps the original block order in
    # the output but decides survival by relevance to the question,
    # protecting the applicable-rules/conclusion blocks -- a no-op when
    # everything already fits.
    from code_intelligence.agent.context import PER_TOOL_OBSERVATION_CAPS
    from code_intelligence.agent.tool_helpers import get_current_question
    body_budget = max(0, PER_TOOL_OBSERVATION_CAPS.get("evaluate_record_rules", 3000) - len(header_text) - 1)
    body = assemble_relevance_ranked_blocks(
        body_blocks, body_budget, question=get_current_question(), separator="\n",
    )
    summary_text = header_text + "\n" + body

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
