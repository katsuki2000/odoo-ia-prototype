"""Deterministic scoring of a synthesized answer against frozen tool evidence."""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from core.output import _detect_any_degenerate_repetition

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+")
MIN_IDENTIFIER_LENGTH = 5
_SENTENCE_BREAK = re.compile(r"[.!?\n]+")
_NEGATION = re.compile(r"\b(?:aucune?|pas de|sans|n'y a|n'existe|n'appara[iî]t|no|not|none|without)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ClaimRule:
    name: str
    claim: "re.Pattern[str]"
    evidence: "re.Pattern[str]"


CLAIM_RULES = (
    ClaimRule(
        name="sql_constraint",
        claim=re.compile(r"contraintes?\s+sql|sql\s+constraints?", re.IGNORECASE),
        evidence=re.compile(r"odoo-sql-constraints-declaration|_sql_constraints\s*=", re.IGNORECASE),
    ),
)


@dataclass
class SynthesisScore:
    think_leak: bool
    degenerate: bool
    answer_chars: int
    reachable_reference_ids: int
    identifier_recall: Optional[float]
    unsupported_identifiers: List[str] = field(default_factory=list)
    unsupported_claims: List[str] = field(default_factory=list)


def strip_thinking(text: str) -> Tuple[str, bool]:
    visible = _THINK_BLOCK.sub("", text)
    visible = _UNCLOSED_THINK.sub("", visible)
    return visible.strip(), visible.strip() != text.strip()


def extract_identifiers(text: str) -> Set[str]:
    return {
        token for token in _IDENTIFIER.findall(text.lower())
        if len(token) >= MIN_IDENTIFIER_LENGTH
    }


def find_unsupported_claims(answer: str, evidence: str) -> List[str]:
    sentences = [part for part in _SENTENCE_BREAK.split(answer) if part.strip()]
    return [
        rule.name for rule in CLAIM_RULES
        if not rule.evidence.search(evidence)
        and any(rule.claim.search(sentence) and not _NEGATION.search(sentence) for sentence in sentences)
    ]


def score_answer(answer: str, frozen_prompt: str, reference_answer: str) -> SynthesisScore:
    visible, think_leak = strip_thinking(answer)
    answer_ids = extract_identifiers(visible)
    evidence_ids = extract_identifiers(frozen_prompt)
    reachable = extract_identifiers(reference_answer) & evidence_ids
    recall = len(reachable & answer_ids) / len(reachable) if reachable else None
    return SynthesisScore(
        think_leak=think_leak,
        degenerate=_detect_any_degenerate_repetition(visible),
        answer_chars=len(visible),
        reachable_reference_ids=len(reachable),
        identifier_recall=recall,
        unsupported_identifiers=sorted(answer_ids - evidence_ids),
        unsupported_claims=find_unsupported_claims(visible, frozen_prompt),
    )
