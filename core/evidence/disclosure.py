"""Disclosure filter of the structured evidence dossier."""


def filter_disclosed_evidence(evidence, allowed: bool):
    """Apply the same disclosure decision to the structured dossier."""
    return [item for item in evidence if allowed or not item.scope.get('sensitive', False)]
