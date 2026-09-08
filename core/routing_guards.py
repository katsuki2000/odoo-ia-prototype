"""Input validation, safety guardrails, and extraction defense for query routing."""

import re
from core.routing_keywords import OUT_OF_SCOPE_TERMS, _ARITHMETIC_ONLY_RE

_MASSIVE_EXTRACTION_PATTERNS = [
    r"toutes?\s+les?\s+règl(es|ements)",
    r"tous\s+les\s+modèles",
    r"tous\s+les\s+modules",
    r"chaque\s+modèle",
    r"l'intégralité\s+du\s+code",
    r"dump\s+de\s+tous",
    r"liste\s+complète\s+de\s+tous",
    r"tous\s+les\s+mots\s+de\s+passe",
    r"(?:liste|dump|export|afficher?|donne)\w*\s+(?:de\s+)?tous\s+les\s+utilisateurs",
    r"tous\s+les\s+utilisateurs\s+et\s+(?:leurs\s+)?mots\s+de\s+passe",
    r"extraire?\s+tout",
    r"toutes\s+les\s+actions\s+serveur",
    r"all\s+rules\s+of\s+all\s+models",
    r"dump\s+all\s+models",
    r"dump\s+all\s+rules",
    r"list\s+all\s+models",
    r"extract\s+all\s+code",
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


def _is_out_of_scope(question: str) -> bool:
    """Reject obvious non-work questions before the LLM can improvise."""
    normalized = question.lower().strip()
    if not normalized:
        return False
    if _ARITHMETIC_ONLY_RE.match(normalized):
        return True
    return any(term in normalized for term in OUT_OF_SCOPE_TERMS)


def _is_massive_extraction_request(question: str) -> bool:
    """Detect queries attempting bulk metadata or rule extraction across models."""
    q = question.lower().strip()
    if not q:
        return False

    bulk_scopes = [
        "tous les modèles", "tous les modules", "chaque modèle",
        "tout le système", "all models", "all modules", "whole database",
    ]
    bulk_targets = [
        "toutes les règles", "tous les accès", "tous les droits",
        "all rules", "all permissions", "all access",
    ]
    if any(s in q for s in bulk_scopes) and any(t in q for t in bulk_targets):
        return True

    return any(re.search(pat, q) for pat in _MASSIVE_EXTRACTION_PATTERNS)


def _is_prompt_injection(question: str) -> bool:
    """Detect prompt injection and system prompt reveal attempts."""
    q = question.lower().strip()
    if not q:
        return False
    return any(re.search(pat, q) for pat in _PROMPT_INJECTION_PATTERNS)
