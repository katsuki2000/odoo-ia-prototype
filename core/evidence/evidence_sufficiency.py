"""
core/evidence_sufficiency.py

Bloc P1 reorientation (todo/contexte.txt section 405): post-analysis
evidence sufficiency signal for the code_intelligence_agent branch.

Deliberately distinct from core/evidence_check.py::check_evidence(), which
is a PRE-analysis check of whether business_resolver could resolve the
business concept (RESOLU / NON_RESOLU / CONFLIT), gating the internal
[BUSINESS TERM RESOLVER] pre-dispatch inside code_intelligence_agent. That
existing check_evidence() output is already surfaced as
state["evidence_status"] / AssistantResponse.evidence_status -- this module
deliberately does NOT reuse that name (EvidenceSufficiencyStatus /
"ci_evidence_sufficiency" instead) to avoid silently shadowing an existing,
already-wired field with a different value space.

This module answers a different question, asked AFTER
code_intelligence_agent has actually run its tools and synthesized an
answer: is the answer itself grounded in evidence sufficient to stand on
its own, or should a RAG documentary fallback take over (or complete it) --
the CI-first, RAG-as-last-resort model documented in architecture.md and
confirmed as the target design in todo/contexte.txt section 405?

Explicit three-way distinction (Stagiaire mandate, todo/contexte.txt
section 405 reply): "outil exécuté" != "preuve pertinente trouvée" !=
"réponse suffisamment étayée". A tool call returning a bare "not found"
result is execution without relevant evidence; relevant evidence that the
engine itself flags as unresolved/ambiguous is not the same as a
confidently grounded answer. These are tracked as three separate checks
below rather than collapsed into a single tool_observations-non-empty test.

Tranche 1 scope only: new, isolated code, independently testable,
deterministic (no LLM call, PoC-stage instruction). NOT wired into
core/graph.py's StateGraph yet -- that wiring (the conditional edge routing
to a RAG fallback node whenever status != SUFFICIENT) is Tranche 2.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from code_intelligence.rules.common import NOT_FOUND_MARKER


class EvidenceSufficiencyStatus(str, Enum):
    """Post-analysis verdict on code_intelligence_agent's own output for a
    single turn.

    CONFLICTING was originally kept in the contract but deliberately NOT
    produced (Stagiaire correction, todo/contexte.txt section 405 reply):
    an indeterminate/unresolved verdict (missing context field, dynamic
    getattr/eval dispatch) is an UNDETERMINED state, not a genuine
    contradiction between two valid findings -- collapsing the two would
    give CONFLICTING an overly broad meaning. That distinction still holds
    (see assess_evidence_sufficiency's step 4 below, unchanged: an
    indeterminate marker still maps to INSUFFICIENT, never CONFLICTING).

    H3 wired (todo/plan.md, todo/contexte.txt section 418+): a REAL
    two-facts-disagree signal is now produced when TWO OR MORE resolved
    models each compute their own legitimate can_view_amount_v2 verdict for
    the same turn with DIFFERING outcomes
    (code_intelligence/ci_helpers.py::_detect_can_view_amount_model_conflict)
    -- as opposed to a single model's verdict that the LLM's own prose
    merely misstated, which stays a synthesis-inversion bug, already
    corrected in place by _correct_can_view_amount_contradictions /
    _correct_security_lock_threshold_contradictions / 
    _answer_denies_other_overrides before final_answer reaches this
    function, and deliberately still OUT of scope for CONFLICTING (an
    already-corrected synthesis slip is not "two valid findings
    disagreeing"). This is deliberately the FIRST and narrowest possible
    real-contradiction signal, not a general-purpose detector -- other
    genuine cross-source disagreements (e.g. across different composite
    tools rather than across resolved models of the same tool) remain
    undetected and fall through to SUFFICIENT/INSUFFICIENT as before.
    """
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"


# Known canned refusal strings already emitted verbatim by
# code_intelligence/ci_agent_node.py when the agent has nothing at all to
# go on for the WHOLE turn (as opposed to a single tool observation --
# see _NON_EVIDENCE_OBSERVATION_MARKERS below for that finer-grained case).
# Matched by substring rather than re-derived independently: these ARE the
# agent's own explicit "I have nothing" statements.
_NO_DATA_MARKER = "Je n'ai pas de données disponibles dans le graphe de connaissances"
_OUT_OF_SCOPE_MODEL_MARKER = "n'est pas present dans le corpus indexe par cet outil"

# Markers the agent/deterministic engine itself already emits when relevant
# evidence WAS found but the resulting verdict is explicitly unresolved or
# undetermined -- ci_helpers.py::_force_dynamic_uncertainty_answer and
# ci_helpers.py::_format_can_view_amount_fact's indeterminate branch. Both
# describe an UNDETERMINED state (a needed context field is unknown, or the
# code path depends on a runtime value static analysis cannot follow) --
# NOT two valid findings actively disagreeing with each other. Mapped to
# INSUFFICIENT below, not CONFLICTING (see EvidenceSufficiencyStatus
# docstring for why).
_DYNAMIC_UNCERTAINTY_MARKER = "Je ne peux pas classifier avec certitude"
_INDETERMINATE_FACT_MARKER = "can_view_amount_v2() = indeterminate"

# Substrings marking a SINGLE tool observation as a negative/no-finding
# result -- the tool executed but found nothing relevant to answer with,
# as opposed to a genuine (possibly negative) deterministic finding such as
# "exists in the index but has no explicit workflow state transitions
# defined" (trace_full_inheritance/describe_workflow's own QueryStatus.EMPTY
# wording) or "No _sql_constraints ... detected [Confiance: ÉLEVÉE]"
# (analyze_data_constraints) -- both of those ARE real, citable facts (a
# confirmed absence), not a failed lookup, and are deliberately NOT included
# here.
#
# NOT_FOUND_MARKER is imported from deterministic/common.py (its own existing
# single source of truth for "model/field not found in graph", already used
# verbatim by 6 of the 9 composite tools: who_has_access_to,
# evaluate_record_rules, field_change_impact, button_execution_path,
# trace_full_inheritance, describe_workflow) rather than re-defined here --
# same F-08 duplication lesson the rest of this codebase already follows
# (see e.g. find_model_source_filepaths's own docstring in ci_agent_tools.py).
# Marks a single tool observation as a captured execution exception (the
# ReAct loop's `except Exception as te:` in code_intelligence/ci_agent_node.py,
# f"Error executing {tool_name}: {str(te)}") rather than a clean tool run
# that legitimately found nothing. Named separately from
# _NON_EVIDENCE_OBSERVATION_MARKERS (which still includes it below) so
# _has_execution_failure() below has a single, non-duplicated source of
# truth for this one marker (F-08 duplication lesson) -- a tool crash and a
# clean not-found result are both "non-evidence" for the relevance check,
# but only the former is an execution failure for has_execution_failure.
_EXECUTION_ERROR_MARKER = "Error executing"

_NON_EVIDENCE_OBSERVATION_MARKERS = [
    NOT_FOUND_MARKER,                                          # "was not found in the indexed knowledge graph"
    "in the indexed knowledge graph",                          # covers list_involved_modules' own phrasing ("... in the indexed knowledge graph.")
    "No Python source files located for model",                # analyze_security_locks / analyze_data_constraints
    "No server actions (ir.actions.server) found for model",   # analyze_server_actions
    "No security analysis results for model",                  # analyze_security_locks (files existed but none readable)
    _EXECUTION_ERROR_MARKER,                                    # tool raised an exception at call time
]


@dataclass
class EvidenceSufficiencyResult:
    """Verdict plus a short, ordered trail of the reason(s) it was reached,
    and the relevant/total observation counts that drove the classification
    -- kept human-readable so it can be logged or surfaced in the
    investigation plan / verification widget without re-deriving an
    explanation later."""
    status: EvidenceSufficiencyStatus
    reasons: List[str] = field(default_factory=list)
    relevant_observation_count: int = 0
    total_observation_count: int = 0
    has_execution_failure: bool = False

    def to_display_dict(self) -> dict:
        return {
            "status": self.status.value,
            "reasons": list(self.reasons),
            "relevant_observation_count": self.relevant_observation_count,
            "total_observation_count": self.total_observation_count,
            "has_execution_failure": self.has_execution_failure,
        }


def _is_relevant_observation(observation: str) -> bool:
    """True if a single tool observation carries a genuine finding (positive
    OR confirmed-negative) rather than a failed lookup/execution error."""
    if not observation or not observation.strip():
        return False
    return not any(marker in observation for marker in _NON_EVIDENCE_OBSERVATION_MARKERS)


def _has_execution_failure(tool_observations: List[str]) -> bool:
    """True if at least one observation this turn is a captured ReAct-loop
    execution exception (code_intelligence/ci_agent_node.py's
    `except Exception as te:` -> f"Error executing {tool_name}: {str(te)}"),
    as opposed to a clean tool run that legitimately found nothing.

    Computed independently of and before the priority branches below: it
    must be able to hold regardless of the final status (e.g. SUFFICIENT
    when some observations failed but others still produced relevant
    evidence, INSUFFICIENT when every observation failed) -- see
    todo/contexte.txt section 486.
    """
    return any(_EXECUTION_ERROR_MARKER in o for o in tool_observations)


def assess_evidence_sufficiency(
    tool_observations: List[str],
    hop_count: int,
    final_answer: str,
    conflict_reason: "Optional[str]" = None,
) -> EvidenceSufficiencyResult:
    """
    Post-analysis assessment of code_intelligence_agent's own output for a
    single turn, evaluated in this priority order (first match wins):

      1. The agent emitted one of its own turn-level canned "I have
         nothing" answers (no-data fallback, unindexed model decline) ->
         INSUFFICIENT. This is "no tool produced anything usable at all",
         independent of what individual observations contain.
      2. No tool ever executed this turn (hop_count == 0 / no observations)
         -> INSUFFICIENT. A defensive guard distinct from (1): catches any
         future code path reaching synthesis without a tool call, even
         without one of the two known canned strings.
      3. Tool(s) executed, but EVERY observation reads as a "not found" /
         execution-error / empty result (_is_relevant_observation) ->
         INSUFFICIENT. This is the "outil exécuté != preuve pertinente
         trouvée" case: tools ran, nothing relevant came back.
      4. At least one relevant observation was found, but the agent's own
         deterministic engine or static-analysis guardrail flags the
         resulting verdict as unresolved/undetermined (dynamic-dispatch
         uncertainty, indeterminate can_view_amount_v2 fact) ->
         INSUFFICIENT. This is "preuve pertinente trouvée != réponse
         suffisamment étayée": real evidence exists, but it does not
         resolve to a confident answer -- an UNDETERMINED state (missing
         context, a runtime-dependent branch), not a contradiction between
         two valid findings, so it does NOT map to CONFLICTING (see
         EvidenceSufficiencyStatus docstring). This still wins over (5)
         below even when a caller also passed a conflict_reason: an
         undetermined verdict is a stronger/prior signal than a cross-model
         disagreement, not a peer to arbitrate against.
      5. `conflict_reason` was passed (non-None/non-empty) by the caller ->
         CONFLICTING. H3 (todo/plan.md, todo/contexte.txt section 418+):
         callers compute this via a real deterministic detector -- today,
         code_intelligence/ci_helpers.py::_detect_can_view_amount_model_conflict,
         which fires only when two or more resolved models produced
         DIFFERING can_view_amount_v2 verdicts this turn. This function
         itself never derives conflict_reason -- it only trusts and reports
         what the caller already deterministically established, the same
         discipline as every other check above (substring/marker matches
         against strings already computed elsewhere, never a second,
         independently-drifting re-derivation).
      6. Otherwise -> SUFFICIENT: at least one relevant observation was
         gathered, the final answer carries no unresolved/undetermined
         marker, and no conflict was reported.

    Deterministic only (no LLM call, PoC-stage instruction): every check
    above is a substring/marker match or a trusted caller-supplied flag,
    never a re-derivation of meaning via a second, independently-drifting
    heuristic.

    Never raises: plain data classification over already-computed fields,
    same contract as core/evidence_check.py::check_evidence() (takes
    finished inputs, never touches the graph/LLM itself).
    """
    reasons: List[str] = []
    total = len(tool_observations)
    execution_failure = _has_execution_failure(tool_observations)

    if _NO_DATA_MARKER in final_answer:
        reasons.append("agent emitted its canned no-data fallback answer")
        return EvidenceSufficiencyResult(EvidenceSufficiencyStatus.INSUFFICIENT, reasons, 0, total, execution_failure)

    if _OUT_OF_SCOPE_MODEL_MARKER in final_answer:
        reasons.append("agent declined: target model not indexed in this instance's corpus")
        return EvidenceSufficiencyResult(EvidenceSufficiencyStatus.INSUFFICIENT, reasons, 0, total, execution_failure)

    if total == 0 or hop_count == 0:
        reasons.append("no tool observations gathered (hop_count == 0)")
        return EvidenceSufficiencyResult(EvidenceSufficiencyStatus.INSUFFICIENT, reasons, 0, total, execution_failure)

    relevant = [o for o in tool_observations if _is_relevant_observation(o)]
    if not relevant:
        reasons.append(
            f"{total} tool observation(s) gathered, but every one reads as a "
            f"'not found' / execution-error / empty result -- tool(s) executed, "
            f"no relevant evidence found"
        )
        return EvidenceSufficiencyResult(EvidenceSufficiencyStatus.INSUFFICIENT, reasons, 0, total, execution_failure)

    if _INDETERMINATE_FACT_MARKER in final_answer or _DYNAMIC_UNCERTAINTY_MARKER in final_answer:
        reasons.append(
            "relevant evidence was found, but the deterministic engine or static "
            "analysis itself flags the resulting verdict as unresolved/undetermined "
            "-- not a contradiction between two valid findings, so INSUFFICIENT "
            "rather than CONFLICTING (see EvidenceSufficiencyStatus docstring, H3)"
        )
        return EvidenceSufficiencyResult(
            EvidenceSufficiencyStatus.INSUFFICIENT, reasons, len(relevant), total, execution_failure,
        )

    if conflict_reason:
        reasons.append(
            f"{len(relevant)}/{total} tool observation(s) carry relevant findings, "
            f"but a caller-supplied conflict_reason flags a genuine cross-source "
            f"disagreement (H3): {conflict_reason}"
        )
        return EvidenceSufficiencyResult(
            EvidenceSufficiencyStatus.CONFLICTING, reasons, len(relevant), total, execution_failure,
        )

    reasons.append(
        f"{len(relevant)}/{total} tool observation(s) carry relevant findings, "
        f"hop_count={hop_count}, no unresolved/ambiguous marker in the final answer"
    )
    return EvidenceSufficiencyResult(
        EvidenceSufficiencyStatus.SUFFICIENT, reasons, len(relevant), total, execution_failure,
    )
