"""
core/smalltalk.py

Deterministic detection of pure smalltalk (greetings, thanks, farewells,
conversational filler like "comment ça va ?", and short acknowledgments
like "d'accord"/"entendu") so the graph can skip retrieve()/route()
entirely for these questions instead of falling through to the
DOCUMENTAIRE default -- see todo/contexte.txt section 294 for the
root-cause analysis this addresses.

The "acknowledgment" category (todo/contexte.txt section 301) is
deliberately narrow: it covers only "d'accord", "entendu", "ça marche",
and "très bien" -- the exact 4 words whose raw cosine similarity was
empirically measured (via scripts/_diag_vector_similarity_floor.py) to
exceed VECTOR_SIMILARITY_FLOOR (0.20) on the current degraded embedding
backend (all-MiniLM-L6-v2), causing retrieve() to return noisy,
irrelevant chunks for these questions despite the floor. "ok"/"compris"/
"parfait" were measured in the same batch and stay BELOW the floor
(0/15 chunks), so they are deliberately left out of this gate -- the
existing similarity floor already handles them correctly, no need for a
second mechanism. This list is not a guess: it is calibrated on
measured noise, not intuition (see section 301 for the raw numbers).

classify_smalltalk() only ever returns a classification. It never
rewrites or truncates the question -- the original, untouched question
is still what reaches retrieve()/route()/generate() and gets logged in
retrieval_trace, for any question this module does NOT intercept.
"""

import re
import unicodedata
from typing import Optional

_GREETING_RE = re.compile(
    r"^(bonjour|bonsoir|salut|coucou|hello|hi|hey|yo|morning)\b[\s,!.]*"
)

_THANKS_FAREWELL_RE = re.compile(
    r"\b(merci\s+beaucoup|merci|je\s+vous\s+remercie|au\s+revoir|"
    r"a\s+bientot|a\s+plus|bonne\s+journee|bonne\s+soiree|"
    r"goodbye|bye|thank\s+you|thanks)\b[\s,!.]*$"
)

_CONVERSATIONAL_FILLER_RE = re.compile(
    r"\b(comment\s+(ca|sa)\s+va|"
    r"comment\s+(allez[\s-]vous|vas[\s-]tu)|"
    r"(ca|sa)\s+va)\b[\s,!.?]*"
)

# Narrow, empirically-calibrated list -- see module docstring and
# todo/contexte.txt section 301. Deliberately NOT a general "short reply"
# detector: only the 4 words measured to leak past VECTOR_SIMILARITY_FLOOR.
_ACKNOWLEDGMENT_RE = re.compile(
    r"\b(d\s+accord|entendu|(ca|sa)\s+marche|tres\s+bien)\b[\s,!.]*"
)

_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _fold_accents(text: str) -> str:
    """Strip diacritics (same approach as core/routing.py::_fold_accents,
    duplicated here to avoid a circular import between the two modules)."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def classify_smalltalk(question: str) -> Optional[str]:
    """
    Classify a question as pure smalltalk, or return None.

    Returns:
        "greeting" -- question is only a greeting (with optional filler,
            e.g. "Bonjour, comment ça va ?")
        "thanks_farewell" -- question is only a thanks/farewell, with no
            greeting present (e.g. "Merci beaucoup")
        "acknowledgment" -- question is only one of the 4 empirically-
            calibrated short acknowledgments ("d'accord", "entendu",
            "ça marche", "très bien") -- see section 301 for calibration
        None -- not pure smalltalk (empty question, or content remains
            once greeting/thanks/filler/acknowledgment are stripped --
            e.g. "Bonjour, comment faire une demande de congés ?")
    """
    if not question or not question.strip():
        return None

    normalized = _fold_accents(question.lower().strip())
    normalized = _PUNCTUATION_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    if not normalized:
        return None

    after_greeting = _GREETING_RE.sub("", normalized).strip()
    greeting_matched = after_greeting != normalized

    after_thanks = _THANKS_FAREWELL_RE.sub("", after_greeting).strip()
    thanks_matched = after_thanks != after_greeting

    after_filler = _CONVERSATIONAL_FILLER_RE.sub("", after_thanks).strip()

    after_ack = _ACKNOWLEDGMENT_RE.sub("", after_filler).strip()
    ack_matched = after_ack != after_filler

    remainder = _WHITESPACE_RE.sub(" ", after_ack).strip()

    if remainder != "":
        return None

    if ack_matched:
        return "acknowledgment"
    if thanks_matched and not greeting_matched:
        return "thanks_farewell"
    return "greeting"


SMALLTALK_RESPONSES = {
    "greeting": "Bonjour ! Comment puis-je vous aider avec l'ERP aujourd'hui ?",
    "thanks_farewell": "Avec plaisir ! N'hésitez pas si vous avez d'autres questions.",
    "acknowledgment": "Entendu. Si vous avez une question sur l'ERP, je suis là.",
}
