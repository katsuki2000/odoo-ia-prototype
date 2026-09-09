"""
code_intelligence/answer_text_signals.py

Shared low-level text-signal primitives for synthesized-answer post-processing:
truncation-proximity detection, monetary amount extraction, approval-intent
detection, can_view_amount fact markers, and security-lock condition regexes.
"""

import re
from typing import Optional

# --- Truncation proximity ---------------------------------------------------

_TRUNCATION_MARKER = "\n[... Content truncated for LLM context limit ...]"
_TRUNCATION_PROXIMITY_CHARS = 50


def _match_near_truncation(text: str, start: int, end: int) -> bool:
    """True if [start, end) span in text is within proximity of a truncation marker."""
    window_start = max(0, start - _TRUNCATION_PROXIMITY_CHARS)
    window_end = min(len(text), end + _TRUNCATION_PROXIMITY_CHARS)
    return _TRUNCATION_MARKER in text[window_start:window_end]


# --- Monetary amount extraction ---------------------------------------------

_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:€|eur(?:os?)?\b)", re.IGNORECASE)


def _extract_amount(question: str) -> Optional[float]:
    """Extract first monetary amount mentioned in question as a float, or None."""
    match = _AMOUNT_PATTERN.search(question)
    if not match:
        return None
    raw = match.group(0)
    numeric_part = re.sub(r"(?i)(€|eur(?:os?)?)", "", raw).strip()
    cleaned = numeric_part.replace(" ", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


# --- Approval-intent detection ----------------------------------------------

_APPROVAL_PATTERN = re.compile(
    r"\b(?:approuv\w*|valid\w*|approbation\w*|permission\w*|exig\w*|condition\w*|rembourse\w*)\b",
    re.IGNORECASE,
)


def _question_is_approval_related(question: str) -> bool:
    return bool(_APPROVAL_PATTERN.search(question))


# --- can_view_amount fact markers -------------------------------------------

_CAN_VIEW_FACT_VERDICT_RE = re.compile(
    r"can_view_amount\(\)\s*=\s*(True|False)\s*:\s*l.utilisateur\s+(PEUT|NE PEUT PAS)",
)
_CAN_VIEW_FACT_INDETERMINATE_MARKER = "can_view_amount_v2() = indeterminate"


def _split_before_first_fact_marker(text: str) -> str:
    """Text portion before the first '[FAIT' marker -- the free-prose synthesis."""
    idx = text.find("[FAIT")
    return text if idx == -1 else text[:idx]


def _has_can_view_amount_fact(final_answer: str) -> bool:
    return bool(_CAN_VIEW_FACT_VERDICT_RE.search(final_answer)) or (
        _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    )


# --- Security-lock condition regexes ----------------------------------------

_LOCK_CONDITION_LINE_RE = re.compile(
    r"\*\s*\"[^\"]*\"\s*\(condition\s*:\s*(.*?has_group\([\'\"]([^\'\"]+)[\'\"]\).*?)\)",
    re.IGNORECASE,
)
_AMOUNT_CMP_RE = re.compile(
    r"(?:rec\.)?amount(?:_total)?\s*(>|>=|<|<=)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
