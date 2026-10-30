"""Refusal messages shared by both branches and the prompt injection guard of the system branch."""

import re

OUT_OF_SCOPE_ANSWER = (
    "This question is outside my scope. "
    "I specialize in internal assistance and procedures"
)
PROMPT_INJECTION_REFUSAL_MSG = (
    'Unauthorized request: system instructions and security policies '
    'cannot be altered or disclosed.'
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


def is_prompt_injection(question: str) -> bool:
    """Detect prompt injection and system prompt reveal attempts."""
    return _PROMPT_INJECTION_RE.search(question) is not None
