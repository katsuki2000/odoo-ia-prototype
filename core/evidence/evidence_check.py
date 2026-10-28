from typing import Any


def check_evidence(concept: Any) -> str:
    return "RESOLU" if concept.is_resolved else "NON_RESOLU"
