from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.agent.matching import ResolvedConcept


def check_evidence(concept: "ResolvedConcept") -> str:
    return "RESOLU" if concept.is_resolved else "NON_RESOLU"
