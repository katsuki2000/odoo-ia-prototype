from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.agent.matching import ResolvedConcept


def check_evidence(concept: "ResolvedConcept", concept_resolved_before_rehydration: bool) -> str:
    if concept_resolved_before_rehydration:
        return "RESOLU"
    if not concept.is_resolved:
        return "NON_RESOLU"
    return "RESOLU"
