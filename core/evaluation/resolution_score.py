"""Verdict d'exactitude d'une resolution de sujet contre les modeles attendus d'une question de banque."""

EXACT = "exact"
WRONG = "faux"
ABSTAINED = "abstention"
UNSCORED = "non_note"


def score_resolution(item, resolved_models):
    expected = set(item.get("expected_models") or [])
    if not expected:
        return UNSCORED
    chosen = set(resolved_models)
    if not chosen:
        return ABSTAINED
    allowed = expected | set(item.get("tolerated_models") or [])
    return EXACT if chosen & expected and chosen <= allowed else WRONG
