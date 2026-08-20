"""
rag/evidence_check.py

H3 (Evidence Check) -- Phase 1, observational only (2026-08-20,
todo/contexte.txt).

Design decision made explicitly with the maitre de stage (todo/contexte.txt):
H3 sits AFTER route() has already picked the code_intelligence branch, never
before -- it never changes route_decision. Rejected alternative (H3 before
route(), deciding which branch to dispatch to) collapses into H4 (a business
term resolving to a model does not by itself imply which branch is correct
-- DOC-08's own regression, todo/contexte.txt section 62, is the concrete
proof: "mise a disposition" resolves deterministically to custom.asset.loan,
yet the correct branch is DOCUMENTAIRE, not CODE_INTELLIGENCE). H4 remains
the least-evidenced hypothesis from the section 60/61 finding set; nothing
here assumes or depends on it.

Phase 1 scope, mirroring H1's own first step (contexte.txt section 62,
"volontairement PASSIF cette premiere etape"): compute and EXPOSE a
three-way status (RESOLU / NON_RESOLU / CONFLIT) reconciling the evidence
already available to code_intelligence_agent when it starts -- but do NOT
yet change tool dispatch, system-prompt content, or gating based on it.
Whether/how each status should affect behavior is deferred to a follow-up
step, once this Phase 1 signal has been measured against the adversarial
benchmark (same phasing discipline as H1's own "consuming this signal to
actually change a routing decision is deferred to a follow-up step").

The three statuses, and exactly what each one means:

- RESOLU: code_intelligence_agent's own resolution (resolve_business_term,
  called with a real LLM, inside this branch) succeeded on its own, from
  THIS turn's question text. Highest-trust case -- no rehydration was
  needed at all.
- NON_RESOLU: nothing resolved anywhere -- neither this branch's own
  attempt, nor route()'s earlier no-LLM attempt this same turn, nor (via
  H1b-ii) a reusable concept from the previous turn. The ReAct loop
  proceeds exactly as it always has for an unresolved concept (unchanged
  behavior, Phase 1 is observational only).
- CONFLIT: this branch's own resolution failed, but a concept was
  rehydrated (_rehydrate_sticky_concept, rag/ci_helpers.py) from
  state["resolved_concept"] -- and that dict was itself only available
  because route()'s _sticky_concept_or_resolve REUSED it from the PREVIOUS
  turn's session (state["resolved_concept_reused"] is True, rag/routing.py)
  rather than resolving it from this turn's own question. This is exactly
  the risk named in todo/contexte.txt section 63's H2 discussion: a
  business concept carried over from an earlier, possibly unrelated
  question, now being handed to this turn's tool dispatch as if it were
  authoritative for a question that itself gave no signal for it. Distinct
  from a rehydration sourced from route()'s OWN this-turn resolution (that
  case is RESOLU -- same question's text, just resolved at a cheaper,
  no-LLM tier).

A concept rehydrated from route()'s own this-turn (non-reused) resolution
is RESOLU, not a fourth category -- the text that produced it is still the
CURRENT question's, the rehydration only changed which resolver-tier found
it (no-LLM in route() vs real-LLM in code_intelligence_agent), not which
turn's text it came from.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.business_resolver import ResolvedConcept
    from rag.routing import RAGState


def check_evidence(
    concept: "ResolvedConcept",
    concept_resolved_before_rehydration: bool,
    state: "RAGState",
) -> str:
    """
    Returns one of "RESOLU" / "NON_RESOLU" / "CONFLIT" -- see this module's
    own docstring for the full rationale behind each.

    concept: the FINAL ResolvedConcept code_intelligence_agent is about to
    act on, i.e. AFTER _rehydrate_sticky_concept has already run.
    concept_resolved_before_rehydration: concept.is_resolved as it stood
    BEFORE _rehydrate_sticky_concept was called -- the caller must capture
    this itself, right after resolve_business_term() and before calling
    _rehydrate_sticky_concept(), since this function only ever sees the
    post-rehydration result and cannot tell the two apart on its own (a
    successful fresh resolution and a successful rehydration both leave
    concept.is_resolved True).
    state: RAGState as passed into code_intelligence_agent, read-only here
    -- only state.get("resolved_concept_reused") is consulted (see
    rag/routing.py's RAGState field comment for exactly what it means).
    """
    if concept_resolved_before_rehydration:
        return "RESOLU"
    if not concept.is_resolved:
        return "NON_RESOLU"
    if state.get("resolved_concept_reused"):
        return "CONFLIT"
    return "RESOLU"
