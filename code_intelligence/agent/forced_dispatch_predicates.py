"""
code_intelligence/agent/forced_dispatch_predicates.py

Single source of truth for WHICH (model[, method]) targets the forced
deterministic pre-dispatch in ci_agent_node.py fires each composite tool
on -- reused as-is by the Investigation Planner (investigation_planner.py)
so the plan and the real dispatch can never independently drift apart on
the 4 categories both need to agree on (access, approval/governance,
automation/bypass, structural locks).
Each function answers "which targets would forced pre-dispatch invoke this
tool for" -- not "has it already been invoked this turn" (that bookkeeping
is ReAct-loop-specific, via ci_agent_node.py's own `seen_calls`, and has no
equivalent need in the Planner, which never actually calls a tool).

"""

import re
from typing import List, Tuple

from code_intelligence.agent.context_extractors import (
    _question_is_access_related,
    _question_is_approval_authority_related,
    _question_is_approval_related,
    _extract_amount,
)
from code_intelligence.agent.dispatch_guards import _question_suggests_automation_bypass


def _resolved_models(concept) -> List[str]:
    if concept is None or not getattr(concept, "is_resolved", False):
        return []
    return list(getattr(concept, "resolved_models", None) or [])


_RELATED_LINE_DELETION_RE = re.compile(
    r"\b(?:supprim\w*|effac\w*|unlink)\b[^.!?\n]{0,100}"
    r"\b(?:lign\w*|line items?)\b|"
    r"\b(?:lign\w*|line items?)\b[^.!?\n]{0,100}"
    r"\b(?:supprim\w*|effac\w*|unlink)\b",
    re.IGNORECASE,
)

_RELATED_LINE_QUESTION_RE = re.compile(
    r"\b(?:lign\w*|line items?)\b",
    re.IGNORECASE,
)


def _related_line_models(G, model_name: str) -> List[str]:
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []
    related = []
    for _, field_node, edge_data in G.out_edges(model_node, data=True):
        if edge_data.get("edge_type") != "HAS_FIELD":
            continue
        field = G.nodes[field_node]
        comodel = field.get("comodel_name")
        field_text = f"{field.get('name', '')} {field.get('label', '')}".lower()
        comodel_leaf = comodel.rsplit(".", 1)[-1] if comodel else ""
        if comodel and ("line" in field_text or comodel_leaf.startswith("line")):
            if comodel not in related:
                related.append(comodel)
    return related


def security_locks_targets(concept, G, question: str = "") -> List[str]:
    """Models analyze_security_locks fires on: structural presence of a
    security-relevant source file, independent of question wording."""
    if G is None:
        return []
    from code_intelligence.agent.tool_helpers import (
        find_model_source_filepaths,
        find_security_lock_source_files,
    )

    models = _resolved_models(concept)
    related_deletion = bool(_RELATED_LINE_DELETION_RE.search(question or ""))
    if related_deletion:
        for model in list(models):
            for related in _related_line_models(G, model):
                if related not in models:
                    models.append(related)

    targets = []
    for model in models:
        has_security_source = bool(find_security_lock_source_files(G, model))
        if has_security_source or (related_deletion and find_model_source_filepaths(G, model)):
            targets.append(model)

    return targets if related_deletion else targets[:1]


def data_constraints_targets(concept, G, question: str = "") -> List[str]:
    """Models analyze_data_constraints fires on for constraint questions."""
    if G is None:
        return []

    models = _resolved_models(concept)
    if not _RELATED_LINE_QUESTION_RE.search(question or ""):
        return models

    for model in list(models):
        for related in _related_line_models(G, model):
            if related not in models:
                models.append(related)
    return models


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
    Approval authority is determined by workflow and application guards, not
    by generic CRUD ACL grants."""
    if G is None or not _question_is_access_related(question):
        return []
    if _question_is_approval_authority_related(question):
        return []
    if _question_is_approval_related(question) and _extract_amount(question) is not None:
        lock_governed = set(security_locks_targets(concept, G))
        return [m for m in _resolved_models(concept) if m not in lock_governed]
    return list(_resolved_models(concept))
