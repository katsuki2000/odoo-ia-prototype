"""Disclosure filter of the structured evidence dossier."""


def filter_disclosed_evidence(evidence):
    """Drop the items flagged sensitive: they never reach the answer or the dossier."""
    return [item for item in evidence if not item.scope.get('sensitive', False)]
