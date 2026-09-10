"""
core/confidence_tags.py

Single source of truth for the French confidence-level word used inside the
"[Confiance: ...]" tag that deterministic/heuristic analyzers (security,
data_constraints, server_actions, overrides) inject verbatim into tool
observation text (schema C, cf. todo/contexte.txt Section 626). Before this
module, each call site hardcoded its own label, mixing English ("HIGH") and
French ("FAIBLE") for the same concept.

Distinct from and does not change:
  - AssistantResponse.confidence (core/schemas.py): float 0.0-1.0, turn-level.
  - The "high"/"medium"/"low" English enum that overrides/server_actions
    LLM interpretation prompts require as their strict JSON output contract
    (schema B) -- that contract is untouched, this module only maps its
    values to a display word.
"""

_CONFIDENCE_LABELS = {
    "high": "ÉLEVÉE",
    "medium": "MOYENNE",
    "low": "FAIBLE",
}


def confidence_label(level: str) -> str:
    """Return the canonical French confidence-level word for a "high"/"medium"/"low" value."""
    try:
        return _CONFIDENCE_LABELS[level.lower()]
    except KeyError:
        raise ValueError(f"Unknown confidence level: {level!r}") from None


__all__ = ["confidence_label"]
