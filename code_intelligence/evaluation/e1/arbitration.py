"""Closed-list arbitration contract for E1 (harness only; production arbitration is untouched).

The model answers with the identifier of one candidate, ``NONE`` or ``AMBIGU``. The identifier is
accepted exactly as listed, or without its kind prefix when it matches exactly one candidate.
Every other output is invalid and never yields a resolution.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

LlmCallable = Callable[[str, str], str]

NONE_TOKEN = "NONE"
AMBIGUOUS_TOKEN = "AMBIGU"

SYSTEM_PROMPT = (
    "Tu es un composant de résolution de termes métier d'une instance Odoo. "
    "Tu choisis dans une liste fermée de candidats. L'instance prime sur ta connaissance "
    "générale d'Odoo : base-toi uniquement sur les libellés, le module et les menus fournis. "
    "Tu ne proposes jamais un identifiant qui n'est pas dans la liste."
)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_RAW_LIMIT = 200


class ArbitrationStatus(str, Enum):
    CHOSEN = "CHOSEN"
    NONE = "NONE"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"
    LLM_ERROR = "LLM_ERROR"


@dataclass(frozen=True)
class ArbitrationResult:
    status: ArbitrationStatus
    choice: Optional[str]
    raw: str
    duration_ms: float


def build_user_prompt(question: str, annotated_candidates: Sequence[tuple[str, str]]) -> str:
    """Prompt over (identifier, annotation) pairs; the identifier is the only valid answer token."""
    block = "\n".join(
        f"- {identifier}\n    {annotation}" for identifier, annotation in annotated_candidates
    )
    return (
        f'Question de l\'utilisateur : "{question}"\n\n'
        f"Candidats (liste fermée) :\n{block}\n\n"
        "Réponds UNIQUEMENT par l'identifiant exact d'UN SEUL candidat s'il correspond clairement "
        f"à la question, par {NONE_TOKEN} si aucun ne correspond, ou par {AMBIGUOUS_TOKEN} si "
        "plusieurs correspondent aussi bien. Aucune explication, aucune ponctuation."
    )


def _resolve_bare_identifier(visible: str, candidates: Sequence[str]) -> Optional[str]:
    """Full identifier of the single candidate whose part after the kind prefix equals ``visible``."""
    matches = [candidate for candidate in candidates if candidate.partition(":")[2] == visible]
    return matches[0] if len(matches) == 1 else None


def parse_output(raw: str, candidates: Sequence[str]) -> tuple[ArbitrationStatus, Optional[str]]:
    """Strict reading: a candidate identifier (kind prefix optional when unambiguous), NONE or AMBIGU."""
    visible = _THINK_BLOCK.sub("", raw or "").strip()
    if visible == NONE_TOKEN:
        return ArbitrationStatus.NONE, None
    if visible == AMBIGUOUS_TOKEN:
        return ArbitrationStatus.AMBIGUOUS, None
    if visible in candidates:
        return ArbitrationStatus.CHOSEN, visible
    bare = _resolve_bare_identifier(visible, candidates)
    if bare is not None:
        return ArbitrationStatus.CHOSEN, bare
    return ArbitrationStatus.INVALID, None


def arbitrate(
    question: str,
    annotated_candidates: Sequence[tuple[str, str]],
    llm: LlmCallable,
) -> ArbitrationResult:
    identifiers = [identifier for identifier, _ in annotated_candidates]
    started = time.monotonic()
    try:
        raw = str(llm(SYSTEM_PROMPT, build_user_prompt(question, annotated_candidates)))
    except Exception as exc:  # a failing LLM is a measured outcome, never a silent choice
        return ArbitrationResult(
            ArbitrationStatus.LLM_ERROR, None, f"{type(exc).__name__}: {exc}"[:_RAW_LIMIT],
            (time.monotonic() - started) * 1000,
        )
    status, choice = parse_output(raw, identifiers)
    return ArbitrationResult(status, choice, raw[:_RAW_LIMIT], (time.monotonic() - started) * 1000)
