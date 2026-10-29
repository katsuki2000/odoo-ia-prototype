"""Input guardrails and loop bounds shared by every engine."""

import re
from typing import Optional

CREDENTIAL_REFUSAL_MSG = 'The request exceeds the authorized analysis scope.'
PROMPT_INJECTION_REFUSAL_MSG = (
    'Unauthorized request: system instructions and security policies '
    'cannot be altered or disclosed.'
)
OUT_OF_SCOPE_ANSWER = (
    "This question is outside my scope. "
    "I specialize in internal assistance and procedures"
)

OUT_OF_SCOPE_TERMS = {
    "blague",
    "gâteau",
    "gateau",
    "recette",
    "coupe du monde",
    "poème",
    "poeme",
    "lune",
}

_ARITHMETIC_ONLY_RE = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*[+\-*/]\s*\d+(?:[.,]\d+)?"
    r"(?:\s*[+\-*/]\s*\d+(?:[.,]\d+)?)*"
    r"(?:\s*=\s*\d*(?:[.,]\d+)?)?\s*\??\s*$"
)

REACT_RECURSION_LIMIT = 6

_CREDENTIAL_PATTERNS = [
    r"tous\s+les\s+mots\s+de\s+passe",
    r"tous\s+les\s+utilisateurs\s+et\s+(?:leurs\s+)?mots\s+de\s+passe",
    r"all\s+users\s+and\s+passwords",
]

_PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|previous\s+)*instructions",
    r"override\s+security",
    r"system\s+prompt",
    r"affiche\s+(ton\s+)?prompt\s+système",
    r"montre\s+(moi\s+)?les\s+consignes\s+système",
    r"forget\s+all\s+rules",
    r"bypass\s+all\s+checks",
    r"you\s+are\s+now\s+dan",
    r"jailbreak",
]


def is_out_of_scope(question: str) -> bool:
    """Reject obvious non-work questions before the LLM can improvise."""
    normalized = question.lower().strip()
    if not normalized:
        return False
    if _ARITHMETIC_ONLY_RE.match(normalized):
        return True
    return any(term in normalized for term in OUT_OF_SCOPE_TERMS)


def is_credential_request(question: str) -> bool:
    """Detect requests for passwords: Odoo does not expose them, so the model must not improvise a search."""
    q = question.lower().strip()
    return any(re.search(pat, q) for pat in _CREDENTIAL_PATTERNS)


def is_prompt_injection(question: str) -> bool:
    """Detect prompt injection and system prompt reveal attempts."""
    q = question.lower().strip()
    if not q:
        return False
    return any(re.search(pat, q) for pat in _PROMPT_INJECTION_PATTERNS)


def refusal_message(question: str) -> Optional[str]:
    """Return the refusal answer for a question the ERP data branch must not run, or None to let it through."""
    if is_out_of_scope(question):
        return OUT_OF_SCOPE_ANSWER
    if is_prompt_injection(question):
        return PROMPT_INJECTION_REFUSAL_MSG
    if is_credential_request(question):
        return CREDENTIAL_REFUSAL_MSG
    return None
