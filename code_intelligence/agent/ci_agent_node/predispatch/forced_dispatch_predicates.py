"""
code_intelligence/forced_dispatch_predicates.py

Single source of truth for WHICH (model[, method]) targets the forced
deterministic pre-dispatch in ci_agent_node.py fires each composite tool
on -- reused as-is by the Investigation Planner (investigation_plan.py) so
the plan and the real dispatch can never independently drift apart on the
4 categories both need to agree on (access, approval/governance,
automation/bypass, structural locks). See todo/contexte.txt section 209-210
(Bloc P1 Jour 6).

Each function answers "which targets would forced pre-dispatch invoke this
tool for" -- not "has it already been invoked this turn" (that bookkeeping
is ReAct-loop-specific, via ci_agent_node.py's own `seen_calls`, and has no
equivalent need in the Planner, which never actually calls a tool).
"""

from typing import List, Tuple

from code_intelligence.agent.ci_agent_node.context.context_extractors import (
    _question_is_access_related,
    _question_is_approval_related,
    _extract_amount,
)
from code_intelligence.agent.ci_agent_node.guards.dispatch_utils import _question_suggests_automation_bypass


def _resolved_models(concept) -> List[str]:
    if concept is None or not getattr(concept, "is_resolved", False):
        return []
    return list(getattr(concept, "resolved_models", None) or [])


def security_locks_targets(concept, G) -> List[str]:
    """Models analyze_security_locks fires on: structural presence of a
    security-relevant source file, independent of question wording."""
    if G is None:
        return []
    from code_intelligence.agent.ci_agent_node.context.agent_tools import find_security_lock_source_files
    return [m for m in _resolved_models(concept)[:1] if find_security_lock_source_files(G, m)]


def server_actions_targets(question: str, concept, G) -> List[str]:
    """Models analyze_server_actions fires on: automation/bypass wording
    AND real ServerAction nodes present on the model."""
    if G is None or not _question_suggests_automation_bypass(question):
        return []
    from code_intelligence.agent.ci_agent_node.context.agent_tools import find_server_action_nodes
    return [m for m in _resolved_models(concept) if find_server_action_nodes(G, m)]


def override_chain_targets(question: str, concept, G) -> List[Tuple[str, str]]:
    """(model, method) pairs analyze_method_override_chain fires on:
    approval wording OR method/override wording AND a real override cascade AND at least one actual
    risk finding (unguarded super / unchecked relational chain), capped to
    the top candidate per model via _rank_and_cap_override_methods.
    If the question specifically inquires about compute methods, targets (model, 'compute')."""
    if G is None:
        return []
    import re
    from code_intelligence.agent.ci_agent_node.context.context_extractors import _question_is_method_or_override_related
    is_invoice_generation_q = bool(re.search(r"\b(?:g[eé]n[eé]ration|cr[eé]ation)\s+(?:de\s+|d['’]\s*)?facture\b", question, re.IGNORECASE))
    if not (_question_is_approval_related(question) or _question_is_method_or_override_related(question) or is_invoice_generation_q):
        return []
    from code_intelligence.agent.ci_agent_node.context.agent_tools import find_methods_with_override_cascade
    from code_intelligence.knowledge_rules.overrides import (
        find_methods_with_override_risk_findings,
        _rank_and_cap_override_methods,
    )

    pairs: List[Tuple[str, str]] = []
    is_compute_q = bool(re.search(r"\b(?:compute|calcul[eé]es?)\b", question, re.IGNORECASE))

    for m in _resolved_models(concept):
        if is_compute_q:
            pairs.append((m, "compute"))
            continue
        candidates = find_methods_with_override_cascade(G, m)
        if is_invoice_generation_q:
            if "_create_invoices" in candidates:
                pairs.append((m, "_create_invoices"))
            continue
        flagged = find_methods_with_override_risk_findings(G, m, candidates)
        flagged = _rank_and_cap_override_methods(question, flagged)
        for method in flagged:
            pairs.append((m, method))
    return pairs


def who_has_access_targets(question: str, concept, G) -> List[str]:
    """Models who_has_access_to fires on: access-related wording.
    If the question specifically asks about approval thresholds on a lock-governed model,
    defer to the finer-grained security lock findings. Otherwise, on any general access,
    modification, or creation question, the ACL matrix must be inspected."""
    if G is None or not _question_is_access_related(question):
        return []
    if _question_is_approval_related(question) and _extract_amount(question) is not None:
        lock_governed = set(security_locks_targets(concept, G))
        return [m for m in _resolved_models(concept) if m not in lock_governed]
    return list(_resolved_models(concept))
