"""
code_intelligence/ci_override_cascade.py

Method-override-cascade extraction, backfill, and contradiction-correction
helpers for the Code Intelligence agent.
"""

import logging
import re
from typing import List, Tuple

from code_intelligence.ci_helpers import (
    _amount_present_in_text,
    _match_near_truncation,
    _OVERRIDE_CHAIN_AMOUNT_RE,
)

logger = logging.getLogger(__name__)


_OVERRIDE_MODULE_RE = re.compile(r"module '([\w.]+)'")


def _extract_override_modules(raw_tool_output: str) -> List[str]:
    """Pull every override-cascade module name out of an
    analyze_method_override_chain raw observation in first-seen order, deduplicated."""
    modules: List[str] = []
    for match in _OVERRIDE_MODULE_RE.finditer(raw_tool_output):
        name = match.group(1).strip()
        if name and name not in modules:
            modules.append(name)
    return modules


def _word_boundary_present(marker: str, text: str) -> bool:
    """Check if marker is present as a standalone word/token in text."""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(marker) + r"(?![A-Za-z0-9_])", text) is not None


def _backfill_missing_override_modules(final_answer: str, raw_tool_output: str, question: str = "") -> str:
    """If the raw override-cascade text names a module that never made it into the
    synthesized answer, append it as an explicit, clearly labeled fact."""
    if question:
        from code_intelligence.ci_helpers import (
            _question_is_inheritance_related,
            _question_is_method_or_override_related,
        )
        if not (_question_is_inheritance_related(question) or _question_is_method_or_override_related(question)):
            return final_answer

    modules = _extract_override_modules(raw_tool_output)
    if not modules:
        return final_answer

    missing = [m for m in modules if not _word_boundary_present(m, final_answer)]
    if not missing:
        return final_answer

    module_list = ", ".join(f"'{m}'" for m in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling override-cascade module(s) missing "
        "from synthesized answer: %s",
        module_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut "
        f"également le/les module(s) suivant(s), absent(s) ou mal identifié(s) "
        f"ci-dessus : {module_list}. Fait extrait directement de l'analyse statique "
        f"du code."
    )


def _extract_override_chain_amounts(raw_tool_output: str) -> List[str]:
    """Pull every monetary threshold embedded in a Python comparison inside
    an override-cascade risk finding in first-seen order, deduplicated."""
    amounts: List[str] = []
    override_sections = re.findall(
        r"(?:Cha[iî]ne de surcharge|Override chain).*?(?=\n\n[A-Z\u00c0-\u00dc]|\Z)",
        raw_tool_output,
        re.DOTALL | re.IGNORECASE,
    )
    search_text = "\n".join(override_sections) if override_sections else ""
    for match in _OVERRIDE_CHAIN_AMOUNT_RE.finditer(search_text):
        if _match_near_truncation(search_text, match.start(), match.end()):
            continue
        amount = match.group(1).replace(" ", "").strip()
        if amount and amount not in amounts:
            amounts.append(amount)
    return amounts


def _backfill_missing_override_chain_amount(final_answer: str, raw_tool_output: str) -> str:
    """If an override-cascade finding's monetary threshold never made it into
    the synthesized answer, append it as an explicit, clearly labeled fact."""
    if not _extract_override_modules(raw_tool_output):
        return final_answer

    amounts = _extract_override_chain_amounts(raw_tool_output)
    if not amounts:
        return final_answer

    missing = [a for a in amounts if not _amount_present_in_text(a, final_answer)]
    if not missing:
        return final_answer

    amount_list = ", ".join(f"{a}€" for a in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling override-cascade amount threshold(s) missing "
        "from synthesized answer: %s",
        amount_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode contient "
        f"une condition supplémentaire déclenchée au-delà de {amount_list}, distincte "
        f"du groupe requis ci-dessus. Fait extrait directement de l'analyse statique "
        f"du code."
    )


_OVERRIDE_COUNT_DENIAL_RE = re.compile(
    r"[^.\n]*aucune\s+autre\s+surcharge[^.\n]*\.?"
    r"|[^.\n]*il\s+n['\u2019]y\s+a\s+pas\s+de\s+surcharges?[^.\n]*detectees?[^.\n]*\.?"
)

_OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE = re.compile(
    r"[^.\n]*erreur[^.\n]*ne\s+(?:seront|sera)\s+pas\s+executee?s?[^.\n]*\.?"
)


def _answer_denies_other_overrides(final_answer: str) -> bool:
    """True if final_answer explicitly claims no other override exists."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_COUNT_DENIAL_RE.search(folded))


def _answer_asserts_override_shortcircuit(final_answer: str) -> bool:
    """True if final_answer asserts a specificity-based short-circuit."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE.search(folded))


def _neutralize_override_count_denial(final_answer: str, modules: List[str]) -> str:
    """Replace the sentence denying any other override with the real count and module list."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _OVERRIDE_COUNT_DENIAL_RE.search(folded)
    if not match:
        return final_answer

    modules_list = ", ".join(f"'{m}'" for m in modules)
    replacement = (
        f"Il existe en réalité {len(modules)} surcharges de cette méthode, "
        f"dans les modules suivants : {modules_list}."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _neutralize_override_shortcircuit_sentence(final_answer: str, modules: List[str]) -> str:
    """Replace the sentence asserting a short-circuit with the real execution semantics."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE.search(folded)
    if not match:
        return final_answer

    order = " → ".join(modules) if modules else "l'ordre indiqué par l'outil"
    replacement = (
        f"Odoo n'applique aucun court-circuit basé sur la spécificité ou "
        f"l'absence d'erreur : les surcharges s'exécutent toutes, dans "
        f"l'ordre réel {order}, et l'exécution d'une surcharge ne s'arrête "
        f"que si elle omet d'appeler super() ou lève explicitement une erreur."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _correct_override_cascade_contradictions(final_answer: str, raw_tool_output: str) -> str:
    """Detect contradiction between synthesized prose and override-cascade facts,
    and replace the contradictory sentence in place."""
    modules = _extract_override_modules(raw_tool_output)

    if len(modules) > 1 and _answer_denies_other_overrides(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis denied the existence "
            "of other overrides while %d modules were present in the raw "
            "tool output -- replacing the denial sentence with the real "
            "count and module list.",
            len(modules),
        )
        final_answer = _neutralize_override_count_denial(final_answer, modules)

    if modules and _answer_asserts_override_shortcircuit(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted a "
            "fabricated specificity-based short-circuit for the override "
            "cascade -- replacing the sentence with the real execution semantics."
        )
        final_answer = _neutralize_override_shortcircuit_sentence(final_answer, modules)

    return final_answer


_UNGUARDED_SUPER_RE = re.compile(
    r"SUPER\(\) NON GARD[ÉE].*?module '([\w.]+)'\).*?"
    r"branche conditionnelle \(`([^`]+)`\)"
)


def _extract_unguarded_super_findings(raw_tool_output: str) -> List[Tuple[str, str]]:
    """Extract (module, condition) pairs from SUPER() NON GARDÉ warnings
    in the override-chain analysis output."""
    return _UNGUARDED_SUPER_RE.findall(raw_tool_output)


def _backfill_missing_unguarded_super(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill for SUPER() NON GARDÉ warnings from the
    override-cascade analysis."""
    findings = _extract_unguarded_super_findings(raw_tool_output)
    if not findings:
        return final_answer

    missing_items = []
    for module, condition in findings:
        field_name = condition.rsplit(".", 1)[-1] if "." in condition else condition
        if field_name not in final_answer:
            missing_items.append((module, condition))

    if not missing_items:
        return final_answer

    parts = []
    for module, condition in missing_items:
        parts.append(
            f"module '{module}' : branche conditionnelle `{condition}` "
            f"avec super() rappelé inconditionnellement (risque d'annulation "
            f"silencieuse de cette logique)"
        )

    detail = " ; ".join(parts)
    logger.info(
        "Node [code_intelligence_agent]: backfilling SUPER() NON GARDÉ finding(s) "
        "missing from synthesized answer: %s", detail,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne de "
        f"surcharge : {detail}. "
        f"Fait extrait directement de l'analyse statique du code."
    )


_MAX_OVERRIDE_CASCADE_DISPATCH = 1


def _rank_and_cap_override_methods(question: str, method_names: List[str]) -> List[str]:
    """Rank override-risk-flagged method names by lexical relevance to the
    question and keep only the top candidate."""
    if len(method_names) <= _MAX_OVERRIDE_CASCADE_DISPATCH:
        return method_names
    from rapidfuzz import fuzz
    question_lower = question.lower()
    scored = [
        (name, fuzz.token_set_ratio(question_lower, name.replace("_", " ").lower()))
        for name in method_names
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    kept = [name for name, _score in scored[:_MAX_OVERRIDE_CASCADE_DISPATCH]]
    logger.info(
        "Node [code_intelligence_agent]: override-cascade dispatch capped -- "
        "%d flagged method(s) found, keeping top %d by relevance to the question: %s.",
        len(method_names), _MAX_OVERRIDE_CASCADE_DISPATCH, kept,
    )
    return kept
