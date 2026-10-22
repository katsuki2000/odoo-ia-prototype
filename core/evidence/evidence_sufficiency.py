"""Post-analysis evidence sufficiency signal for the code_intelligence_agent branch.

Distinct from core/evidence_check.py::check_evidence(), the PRE-analysis check of whether the
business concept could be resolved (surfaced as state["evidence_status"]); hence the separate
names EvidenceSufficiencyStatus / "ci_evidence_sufficiency".

Asked AFTER the agent ran its tools and synthesized an answer: is the answer grounded enough to
stand alone, or should the documentary RAG fallback take over (CI first, RAG as last resort,
see architecture.md)? Three separate checks: tool executed != relevant evidence found !=
sufficiently grounded answer. Deterministic only (no LLM call).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from code_intelligence.rules.common import NOT_FOUND_MARKER


class EvidenceSufficiencyStatus(str, Enum):
    """Post-analysis verdict on code_intelligence_agent's own output for one turn.

    CONFLICTING is produced only for a real two-facts-disagree signal: two or more resolved
    models give DIFFERING can_view_amount_v2 verdicts in the same turn
    (ci_helpers.py::_detect_can_view_amount_model_conflict). An indeterminate verdict (missing
    context field, dynamic dispatch) is UNDETERMINED, not a contradiction, and maps to
    INSUFFICIENT. A single verdict the LLM misstated is a synthesis slip, corrected in place
    before this function runs. Other cross-source disagreements are not detected.
    """
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"


# Canned refusal strings the agent emits when it has nothing at all for the WHOLE turn.
_NO_DATA_MARKER = "Je n'ai pas de données disponibles dans le graphe de connaissances"
_OUT_OF_SCOPE_MODEL_MARKER = "n'est pas present dans le corpus indexe par cet outil"

# Markers of a relevant but explicitly undetermined verdict (see EvidenceSufficiencyStatus).
_DYNAMIC_UNCERTAINTY_MARKER = "Je ne peux pas conclure avec certitude"
_INDETERMINATE_FACT_MARKER = "can_view_amount_v2() = indeterminate"

# Substrings marking a SINGLE tool observation as a failed lookup. Confirmed absences such as
# "No workflow state transition could be derived" are real facts and are NOT listed.
# NOT_FOUND_MARKER is the shared "not found in graph" marker from rules/common.py.
# _EXECUTION_ERROR_MARKER marks a captured tool exception (ci_agent_node.py); kept separate so
# _has_execution_failure() shares its single definition.
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
    """Verdict, ordered reasons, and the observation counts that drove the classification."""
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
    """True if at least one observation this turn is a captured tool execution exception.

    Computed independently of the final status: it can hold with SUFFICIENT (other observations
    still produced evidence) or INSUFFICIENT.
    """
    return any(_EXECUTION_ERROR_MARKER in o for o in tool_observations)


def assess_evidence_sufficiency(
    tool_observations: List[str],
    hop_count: int,
    final_answer: str,
    conflict_reason: "Optional[str]" = None,
) -> EvidenceSufficiencyResult:
    """Assess one turn's output; first match wins:

      1. A turn-level canned "nothing" answer (no data, model not indexed) -> INSUFFICIENT.
      2. No tool executed (hop_count == 0 / no observations) -> INSUFFICIENT.
      3. Every observation is a not-found / execution-error / empty result -> INSUFFICIENT.
      4. Relevant evidence, but the final answer carries an unresolved/undetermined marker ->
         INSUFFICIENT. Wins over 5: an undetermined verdict is not a conflict.
      5. `conflict_reason` supplied by the caller -> CONFLICTING. The caller derives it
         deterministically (today: ci_helpers.py::_detect_can_view_amount_model_conflict);
         this function only reports it.
      6. Otherwise SUFFICIENT.

    Deterministic and never raises: substring/marker matches and a trusted caller flag only.
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
