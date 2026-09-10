from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.agent.business_resolver import ResolvedConcept
    from core.routing import RAGState


def check_evidence(
    concept: "ResolvedConcept",
    concept_resolved_before_rehydration: bool,
    state: "RAGState",
) -> str:
    if concept_resolved_before_rehydration:
        return "RESOLU"
    if not concept.is_resolved:
        return "NON_RESOLU"
    if state.get("resolved_concept_reused"):
        return "CONFLIT"
    return "RESOLU"
