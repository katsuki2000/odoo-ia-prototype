# -*- coding: utf-8 -*-
"""
Design decision made explicitly with the maitre de stage: H3 sits AFTER
route() (code_intelligence_agent), never before -- it never changes
route_decision. See rag/evidence_check.py's module docstring for the full
rationale (rejected alternative: H3 before route() collapses into H4, the
least-evidenced hypothesis from  section 60/61).

This file locks check_evidence() itself -- the RESOLU/NON_RESOLU decision.
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

def test_resolved_concept_is_resolu():
    assert check_evidence(_resolved()) == "RESOLU"


def test_unresolved_concept_is_non_resolu():
    assert check_evidence(_unresolved()) == "NON_RESOLU"
