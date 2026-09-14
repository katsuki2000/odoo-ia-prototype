"""
code_intelligence/ci_link_guards.py

Detection, neutralization, and backfill helpers for link-guards,
server-action trigger conditions, and hardcoded bypass IDs.
"""

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

_LINK_GUARD_RE = re.compile(
    r"\[GARDE DE LIEN: si '([^']+)' est vide/absent .*?NE S'APPLIQUE PAS dans ce cas",
    re.DOTALL,
)

_LINK_GUARD_CONTRADICTION_PATTERN = re.compile(
    r"s.?applique\s+(quand\s+meme|tout\s+de\s+meme|malgre|dans\s+tous\s+les\s+cas|"
    r"de\s+toute\s+facon|independamment|meme\s+sans|meme\s+en\s+l.?absence)"
)

_LINK_GUARD_CONTRADICTING_SENTENCE_RE = re.compile(
    r"[^.\n]*s.?applique\s+(?:quand\s+meme|tout\s+de\s+meme|malgre|dans\s+tous\s+les\s+cas|"
    r"de\s+toute\s+facon|independamment|meme\s+sans|meme\s+en\s+l.?absence)[^.\n]*\.?"
)


def _answer_contradicts_link_guard(final_answer: str) -> bool:
    """True if final_answer asserts the rule applies despite an absent guard field."""
    from code_intelligence.rules.group_resolver import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_LINK_GUARD_CONTRADICTION_PATTERN.search(folded))


def _neutralize_contradicting_link_guard_sentence(final_answer: str, guard_fields: List[str]) -> str:
    """Replace sentence asserting wrong link-guard conclusion with correct one."""
    from code_intelligence.rules.group_resolver import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _LINK_GUARD_CONTRADICTING_SENTENCE_RE.search(folded)
    if not match:
        return final_answer

    fields_list = ", ".join(f"'{g}'" for g in guard_fields)
    replacement = (
        f"La règle NE s'applique PAS en l'absence de {fields_list} "
        f"(court-circuit Python : un champ vide/absent en première position "
        f"d'un `and` rend toute la condition fausse)."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _extract_link_guard_fields(raw_tool_output: str) -> List[str]:
    """Pull every [GARDE DE LIEN] guarding field name out of raw tool text."""
    fields: List[str] = []
    for match in _LINK_GUARD_RE.finditer(raw_tool_output):
        name = match.group(1).strip()
        if name and name not in fields:
            fields.append(name)
    return fields


_TRIGGER_CONDITION_RE = re.compile(r"\u26a1 Condition\(s\) de d\u00e9clenchement\s*:\s*(.+)")
_TRIGGER_CONDITION_LITERAL_RE = re.compile(r"'([^']+)'")


def _extract_trigger_condition_literals(raw_tool_output: str) -> List[str]:
    """Extract quoted string literals from server-action trigger condition lines."""
    match = _TRIGGER_CONDITION_RE.search(raw_tool_output)
    if not match:
        return []
    literals: List[str] = []
    for lit_match in _TRIGGER_CONDITION_LITERAL_RE.finditer(match.group(1)):
        lit = lit_match.group(1)
        if lit and lit not in literals:
            literals.append(lit)
    return literals


def _backfill_missing_trigger_condition_literals(final_answer: str, raw_tool_output: str) -> str:
    """Backfill missing string literals from server action trigger condition."""
    literals = _extract_trigger_condition_literals(raw_tool_output)
    if not literals:
        return final_answer

    missing = [lit for lit in literals if lit not in final_answer]
    if not missing:
        return final_answer

    lit_list = ", ".join(f"`{lit}`" for lit in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling server-action trigger-condition "
        "literal(s) missing from synthesized answer: %s",
        lit_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT D\u00c9TERMINISTIQUE] Valeur(s) litt\u00e9rale(s) de la condition de "
        f"d\u00e9clenchement de l'action serveur, absente(s) de la reformulation "
        f"ci-dessus : {lit_list}. Fait extrait directement de l'analyse statique "
        f"du code."
    )


_HARDCODED_IDS_LINE_RE = re.compile(r"IDs en dur\s*:\s*\[([^\]]+)\]")


def _extract_hardcoded_id_literals(raw_tool_output: str) -> List[str]:
    """Extract hardcoded IDs from server action bypass lines."""
    match = _HARDCODED_IDS_LINE_RE.search(raw_tool_output)
    if not match:
        return []
    ids: List[str] = []
    for raw_id in match.group(1).split(","):
        raw_id = raw_id.strip()
        if raw_id and raw_id not in ids:
            ids.append(raw_id)
    return ids


def _backfill_missing_hardcoded_id_literals(final_answer: str, raw_tool_output: str) -> str:
    """Backfill missing hardcoded IDs from server action bypass lines."""
    from code_intelligence.rules.security_locks import _amount_present_in_text

    ids = _extract_hardcoded_id_literals(raw_tool_output)
    if not ids:
        return final_answer

    missing = [i for i in ids if not _amount_present_in_text(i, final_answer)]
    if not missing:
        return final_answer

    id_list = ", ".join(missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling hardcoded privileged-ID "
        "literal(s) missing from synthesized answer: %s",
        id_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT D\u00c9TERMINISTIQUE] Valeur(s) litt\u00e9rale(s) des identifiants "
        f"cod\u00e9s en dur b\u00e9n\u00e9ficiant du contournement, absente(s) de la "
        f"reformulation ci-dessus : {id_list}. Fait extrait directement de "
        f"l'analyse statique du code."
    )


def _backfill_link_guard_clarifications(final_answer: str, raw_tool_output: str, question: Optional[str] = None) -> str:
    """Deterministic backfill whenever a [GARDE DE LIEN] annotation is present."""
    guard_fields = _extract_link_guard_fields(raw_tool_output)
    if not guard_fields:
        return final_answer

    if question is not None and not any(
        re.search(rf"\b{re.escape(g.lower())}\b", question.lower())
        or re.search(rf"\b{re.escape(g.lower())}\b", final_answer.lower())
        for g in guard_fields
    ):
        return final_answer

    marker = "[FAIT DÉTERMINISTIQUE] Court-circuit"
    if marker in final_answer:
        return final_answer

    fields_list = ", ".join(f"'{g}'" for g in guard_fields)

    if _answer_contradicts_link_guard(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis contradicted its own "
            "link-guard short-circuit conclusion for field(s) %s -- replacing "
            "the contradicting sentence with the correct conclusion.",
            fields_list,
        )
        final_answer = _neutralize_contradicting_link_guard_sentence(final_answer, guard_fields)

    logger.info(
        "Node [code_intelligence_agent]: appending deterministic link-guard "
        "clarification for field(s): %s",
        fields_list,
    )
    return (
        final_answer
        + f"\n\n{marker} ET (déterministe) : l'analyse statique du code montre que "
        f"la condition dépend de {fields_list} en première position d'un `and` -- si ce "
        f"champ est vide ou absent (aucun enregistrement lié), toute la condition est "
        f"FAUSSE par court-circuit Python, et la règle correspondante NE S'APPLIQUE PAS, "
        f"quel que soit le reste de la condition (montant, etc.). Fait extrait directement "
        f"de l'analyse statique du code, indépendant de toute reformulation en langage naturel."
    )
