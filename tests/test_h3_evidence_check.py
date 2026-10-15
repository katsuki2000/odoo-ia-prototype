# -*- coding: utf-8 -*-
"""
Design decision made explicitly with the maitre de stage: H3 sits AFTER
route() (code_intelligence_agent), never before -- it never changes
route_decision. See rag/evidence_check.py's module docstring for the full
rationale (rejected alternative: H3 before route() collapses into H4, the
least-evidenced hypothesis from  section 60/61).

This file locks check_evidence() itself -- the RESOLU/NON_RESOLU decision,
given the concept and whether it resolved before rehydration.
"""
from code_intelligence.agent.matching import ResolvedConcept
from core.evidence.evidence_check import check_evidence


def _unresolved(user_term="et pour cette annee ?") -> ResolvedConcept:
    return ResolvedConcept(user_term=user_term, is_resolved=False, source_step="unresolved")


def _resolved(user_term="facture", models=None) -> ResolvedConcept:
    return ResolvedConcept(
        user_term=user_term,
        resolved_models=models or ["account.move"],
        confidence=1.0,
        source_step="static_alias",
        is_resolved=True,
        reason=f"Matched static aliases: {user_term}",
    )


# ── check_evidence() ────────────────────────────────────────────────────────

def test_resolved_before_rehydration_is_resolu_regardless_of_state():
    """Highest-trust case: this branch's own resolution succeeded on its
    own -- state is irrelevant, never even consulted for the reused flag."""
    concept = _resolved()
    status = check_evidence(concept, True)
    assert status == "RESOLU"


def test_still_unresolved_after_rehydration_is_non_resolu():
    concept = _unresolved()
    status = check_evidence(concept, False)
    assert status == "NON_RESOLU"


def test_rehydrated_from_this_turns_own_route_resolution_is_resolu():
    """Rehydrated (this branch's own attempt failed), but NOT reused from
    a previous turn -- route()'s own no-LLM resolution of THIS question's
    text found it. Still the current question's own text, just resolved at
    a cheaper tier -- RESOLU, not CONFLIT."""
    concept = _resolved()  # what _rehydrate_sticky_concept would have produced
    status = check_evidence(concept, False)
    assert status == "RESOLU"
