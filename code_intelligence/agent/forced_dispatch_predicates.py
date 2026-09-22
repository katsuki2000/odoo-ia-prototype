"""
code_intelligence/agent/forced_dispatch_predicates.py

Single source of truth for WHICH (model[, method]) targets the forced
deterministic pre-dispatch in ci_agent_node.py fires each composite tool
on -- reused as-is by the Investigation Planner (investigation_planner.py)
so the plan and the real dispatch can never independently drift apart on
the 4 categories both need to agree on (access, approval/governance,
automation/bypass, structural locks). See todo/contexte.txt section 209-210
(Bloc P1 Jour 6).

Each function answers "which targets would forced pre-dispatch invoke this
tool for" -- not "has it already been invoked this turn" (that bookkeeping
is ReAct-loop-specific, via ci_agent_node.py's own `seen_calls`, and has no
equivalent need in the Planner, which never actually calls a tool).

Kept as its own leaf module (Section 733 restoration): predispatch.py
imports at module level from predispatch_access.py and predispatch_actions.py,
and those two modules import these predicates back -- a real cycle if the
predicates lived inside predispatch.py itself. The Option C merge had
collapsed this file into predispatch.py, which silently broke every
`from .forced_dispatch_predicates import ...` deferred import in
predispatch_access.py/predispatch_actions.py (ModuleNotFoundError) and left
investigation_planner.py's own import of these symbols from
`code_intelligence.agent.predispatch` degrading silently to conservative
defaults on any exception (its own try/except around that import block).
"""

from typing import List, Tuple

from code_intelligence.agent.context_extractors import (
    _question_is_access_related,
    _question_is_approval_related,
    _extract_amount,
)
from code_intelligence.agent.dispatch_guards import _question_suggests_automation_bypass


def _resolved_models(concept) -> List[str]:
    if concept is None or not getattr(concept, "is_resolved", False):
        return []
    return list(getattr(concept, "resolved_models", None) or [])


def security_locks_targets(concept, G) -> List[str]:
    """Models analyze_security_locks fires on: structural presence of a
    security-relevant source file, independent of question wording."""
    if G is None:
        return []
    from code_intelligence.agent.tool_helpers import find_security_lock_source_files
    return [m for m in _resolved_models(concept)[:1] if find_security_lock_source_files(G, m)]


def server_actions_targets(question: str, concept, G) -> List[str]:
    """Models analyze_server_actions fires on: automation/bypass wording
    AND real ServerAction nodes present on the model."""
    if G is None or not _question_suggests_automation_bypass(question):
        return []
    from code_intelligence.agent.tool_helpers import find_server_action_nodes
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
    from code_intelligence.agent.context_extractors import _question_is_method_or_override_related
    is_invoice_generation_q = bool(re.search(r"\b(?:g[eé]n[eé]ration|cr[eé]ation)\s+(?:de\s+|d['’]\s*)?facture\b", question, re.IGNORECASE))
    # Section 883: la wording d'approbation seule est trop large (PUR-Q1 :
    # "distingue... acheteur d'un manager", aucun montant -- dispatchait
    # analyze_method_override_chain sur une methode sans rapport, privant la
    # garde de distinction securitaire de son budget de hops). Meme gate que
    # who_has_access_targets (l.108) : n'exiger la wording d'approbation que
    # si un montant est cite (contournement de seuil, cas custom_credit_note_
    # approval_vip). method_or_override et invoice_generation restent
    # independants du montant.
    is_approval_with_amount_q = (
        _question_is_approval_related(question) and _extract_amount(question) is not None
    )
    if not (is_approval_with_amount_q or _question_is_method_or_override_related(question) or is_invoice_generation_q):
        return []
    from code_intelligence.agent.tool_helpers import find_methods_with_override_cascade
    from code_intelligence.rules.overrides import (
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
