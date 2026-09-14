"""AST static analysis check for unchecked relational field chains in method overrides."""

import ast
import logging
from pathlib import Path
from typing import List, Optional

import networkx as nx

from code_intelligence.rules.override_unguarded import resolve_method_override_chain
from code_intelligence.rules.override_unguarded import detect_unguarded_super
from core.output import confidence_label

_logger = logging.getLogger(__name__)

_RELATIONAL_CHAIN_MIN_DEPTH = 4


def _attribute_chain_depth(node: ast.Attribute) -> int:
    depth = 0
    cur = node
    while isinstance(cur, ast.Attribute):
        depth += 1
        cur = cur.value
    return depth


def _attribute_chain_names(node: ast.Attribute) -> List[str]:
    names = []
    cur = node
    while isinstance(cur, ast.Attribute):
        names.append(cur.attr)
        cur = cur.value
    return list(reversed(names))


class _UncheckedRelationalChainVisitor(ast.NodeVisitor):
    def __init__(self):
        self.checked_names: set = set()
        self.long_chains: List[tuple] = []

    def visit_If(self, node: ast.If):
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Attribute):
                self.checked_names.add(sub.attr)
            elif isinstance(sub, ast.Name):
                self.checked_names.add(sub.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        depth = _attribute_chain_depth(node)
        if depth >= _RELATIONAL_CHAIN_MIN_DEPTH:
            names = _attribute_chain_names(node)
            self.long_chains.append((node.lineno, ".".join(names), names))
        for child in ast.iter_child_nodes(node):
            if child is not node.value:
                self.visit(child)


def _find_guarding_condition_for_helper_call(
    func: ast.FunctionDef, helper_name: str
) -> Optional[str]:
    result: Optional[str] = None

    class _GuardFinder(ast.NodeVisitor):
        def __init__(self):
            self._if_test_stack: List[ast.expr] = []

        def visit_If(self, node: ast.If):
            self._if_test_stack.append(node.test)
            self.generic_visit(node)
            self._if_test_stack.pop()

        def visit_Call(self, node: ast.Call):
            nonlocal result
            if (
                result is None
                and self._if_test_stack
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == helper_name
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                try:
                    result = ast.unparse(self._if_test_stack[-1])
                except Exception:
                    result = None
            self.generic_visit(node)

    _GuardFinder().visit(func)
    return result


def detect_unchecked_relational_chain(
    source: str, filepath: str, method_name: str, target_lineno: int, module: str = ""
) -> Optional[str]:
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as e:
        _logger.warning("Could not parse %s for relational-chain analysis: %s", filepath, e)
        return None

    target_func = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == method_name
            and node.lineno == target_lineno
        ):
            target_func = node
            break

    if target_func is None:
        return None

    candidates = [target_func]
    called_helper_names = {
        n.func.attr
        for n in ast.walk(target_func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "self"
    }
    if called_helper_names:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in called_helper_names:
                candidates.append(node)

    findings = []
    for func in candidates:
        guarding_condition = None
        if func is not target_func:
            guarding_condition = _find_guarding_condition_for_helper_call(
                target_func, func.name
            )
        visitor = _UncheckedRelationalChainVisitor()
        visitor.visit(func)
        for lineno, dotted, names in visitor.long_chains:
            if not any(n in visitor.checked_names for n in names):
                findings.append((func.name, lineno, dotted, guarding_condition))

    if not findings:
        return None

    detail_parts = []
    for fn, ln, path, condition in findings:
        part = f"{fn}() L{ln}: `{path}`"
        if condition:
            part += f" (atteint si `{condition}`)"
        detail_parts.append(part)
    detail = "; ".join(detail_parts)
    return (
        "CHAINE RELATIONNELLE NON V\u00c9RIFI\u00c9E (R\u00e8gle 3): "
        f"'{method_name}' (module '{module}') d\u00e9pend d'une cha\u00eene de champs "
        f"Many2one encha\u00een\u00e9s sans v\u00e9rification d'existence -- {detail}. Si un "
        "maillon interm\u00e9diaire est vide, l'expression compl\u00e8te s'\u00e9value "
        "silencieusement \u00e0 False/un recordset vide, sans erreur -- risque r\u00e9el "
        "que la personne cens\u00e9e \u00eatre notifi\u00e9e/valider ne le soit jamais, sans "
        f"signal d'erreur. [Confiance: {confidence_label('low')} -- heuristique statique, ne "
        "v\u00e9rifie pas si un garde est exprim\u00e9 ailleurs dans l'appelant]"
    )


def find_methods_with_override_risk_findings(
    G: nx.DiGraph, model_name: str, method_names: List[str]
) -> List[str]:
    hits: List[str] = []
    for method_name in method_names:
        sites = resolve_method_override_chain(G, model_name, method_name)
        for site in sites:
            p = Path(site.filepath)
            if not p.exists():
                continue
            try:
                source = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if detect_unguarded_super(
                source, site.filepath, method_name, site.lineno, module=site.module
            ) or detect_unchecked_relational_chain(
                source, site.filepath, method_name, site.lineno, module=site.module
            ):
                hits.append(method_name)
                break
    return hits


find_methods_with_unguarded_super_and_relational_risk = find_methods_with_override_risk_findings
find_methods_with_unguarded_super = find_methods_with_override_risk_findings

# ── Override Cascade ─────────────────────────────────────────────────────

"""
code_intelligence/ci_override_cascade.py

Method-override-cascade extraction, backfill, and contradiction-correction
helpers for the Code Intelligence agent.
"""

import logging
import re
from typing import List, Tuple

from code_intelligence.rules.security_locks import (
    _amount_present_in_text,
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
        from code_intelligence.agent.context_extractors import (
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
    from code_intelligence.agent.context import _match_near_truncation
    override_sections = re.findall(
        r"(?:Cha[iî]ne de surcharge|Override chain).*?(?=\n\n[A-Z\u00c0-\u00dc]|\Z)",
        raw_tool_output,
        re.DOTALL | re.IGNORECASE,
    )
    search_text = "\n".join(override_sections) if override_sections else raw_tool_output
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
    from code_intelligence.rules.group_resolver import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_COUNT_DENIAL_RE.search(folded))


def _answer_asserts_override_shortcircuit(final_answer: str) -> bool:
    """True if final_answer asserts a specificity-based short-circuit."""
    from code_intelligence.rules.group_resolver import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE.search(folded))


def _neutralize_override_count_denial(final_answer: str, modules: List[str]) -> str:
    """Replace the sentence denying any other override with the real count and module list."""
    from code_intelligence.rules.group_resolver import _fold_accents
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
    from code_intelligence.rules.group_resolver import _fold_accents
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
