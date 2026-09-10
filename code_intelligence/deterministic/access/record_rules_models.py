"""
code_intelligence/deterministic/record_rules_models.py

Data structures and evaluation result models for Odoo ir.rule record rules.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Tuple

from code_intelligence.deterministic.access.domain_evaluator import (
    _kleene_and,
    _kleene_or,
    evaluate_domain_force,
)
from core.evidence import Evidence


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
