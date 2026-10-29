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

REACT_RECURSION_LIMIT = 6

OUT_OF_SCOPE_TERMS = (
    "blague",
    "gâteau",
    "gateau",
    "gâteaux",
    "gateaux",
    "recette",
    "coupe du monde",
    "poème",
    "poeme",
    "lune",
)

# Whole words only: a bare substring would refuse "lunettes" (a product) because of "lune".
_OUT_OF_SCOPE_RE = re.compile(r"\b(?:" + "|".join(map(re.escape, OUT_OF_SCOPE_TERMS)) + r")s?\b")

_ARITHMETIC_ONLY_RE = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*[+\-*/]\s*\d+(?:[.,]\d+)?"
    r"(?:\s*[+\-*/]\s*\d+(?:[.,]\d+)?)*"
    r"(?:\s*=\s*\d*(?:[.,]\d+)?)?\s*\??\s*$"
)

_CREDENTIAL_RE = re.compile(
    r"tous\s+les\s+mots\s+de\s+passe"
    r"|tous\s+les\s+utilisateurs\s+et\s+(?:leurs\s+)?mots\s+de\s+passe"
    r"|all\s+users\s+and\s+passwords",
    re.IGNORECASE,
)

_PROMPT_INJECTION_RE = re.compile(
    r"ignore\s+(?:all\s+|previous\s+)*instructions"
    r"|override\s+security"
    r"|system\s+prompt"
    r"|affiche\s+(?:ton\s+)?prompt\s+système"
    r"|montre\s+(?:moi\s+)?les\s+consignes\s+système"
    r"|forget\s+all\s+rules"
    r"|bypass\s+all\s+checks"
    r"|you\s+are\s+now\s+dan\b"
    r"|jailbreak",
    re.IGNORECASE,
)


def is_out_of_scope(question: str) -> bool:
    """Reject obvious non-work questions before the LLM can improvise."""
    normalized = question.lower()
    return bool(_ARITHMETIC_ONLY_RE.match(normalized) or _OUT_OF_SCOPE_RE.search(normalized))


def is_credential_request(question: str) -> bool:
    """Odoo does not expose passwords, so the model must not improvise a search."""
    return _CREDENTIAL_RE.search(question) is not None


def is_prompt_injection(question: str) -> bool:
    """Detect prompt injection and system prompt reveal attempts."""
    return _PROMPT_INJECTION_RE.search(question) is not None


def refusal_message(question: str) -> Optional[str]:
    """Return the refusal answer for a question the ERP data branch must not run, or None to let it through."""
    if is_out_of_scope(question):
        return OUT_OF_SCOPE_ANSWER
    if is_prompt_injection(question):
        return PROMPT_INJECTION_REFUSAL_MSG
    if is_credential_request(question):
        return CREDENTIAL_REFUSAL_MSG
    return None
