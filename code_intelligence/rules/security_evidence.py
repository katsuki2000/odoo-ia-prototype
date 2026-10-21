"""Located security observations, not inferred authorization verdicts."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from core.output import confidence_label
from code_intelligence.agent.context import _truncate_observation
from code_intelligence.agent.tool_helpers import get_current_question
from code_intelligence.rules.relevance_budget import (
    _protected_prefix_end, _rerank_by_relevance, _waterfill_with_protected_minimum,
)

if TYPE_CHECKING:
    from code_intelligence.rules.security import PythonSecurityLockAnalysis

logger = logging.getLogger(__name__)
_EXCEPTION_MESSAGES_MARKER = '  - Security lock messages'
_METHOD_FAMILY_VERBS_FR = {
    'unlink': re.compile(r'supprim\w*|effac\w*|\bdelete\b', re.IGNORECASE),
    'cancel': re.compile(r'annul\w*|\bcancel\w*\b', re.IGNORECASE),
    'confirm': re.compile(r'confirm\w*|valid\w*', re.IGNORECASE),
    'approve': re.compile(r'approuv\w*|\bapprove\w*\b', re.IGNORECASE),
    'lock': re.compile(r'verrouill\w*|\block\w*\b', re.IGNORECASE),
    'unlock': re.compile(r'd[ée]verrouill\w*|\bunlock\w*\b', re.IGNORECASE),
    'create': re.compile(r'cr[ée][ée]?r?\w*', re.IGNORECASE),
    'write': re.compile(r'modifi\w*|[ée]dit\w*|chang\w*', re.IGNORECASE),
}
_METHOD_FAMILY_BONUS = 100.0


def _method_family_bonus(method_name: str, question: Optional[str]) -> float:
    if not method_name or not question:
        return 0.0
    return _METHOD_FAMILY_BONUS if any(
        family in method_name.lower() and pattern.search(question)
        for family, pattern in _METHOD_FAMILY_VERBS_FR.items()) else 0.0


def build_security_lock_evidence(filepath: str, hardcoded_logins: List[str], exception_messages: List[str],
    exception_conditions: List[str], exception_guard_fields: List[str], exception_linenos: List[int],
    required_groups: List[str], required_group_methods: List[str], required_group_linenos: List[int],
    dynamic_dispatch_types: List[str], required_group_is_gating: Optional[List[bool]] = None,
    required_group_alt_conditions: Optional[List[str]] = None, exception_methods: Optional[List[str]] = None) -> List[Evidence]:
    evidence = []
    evidence.append(make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(f"File '{filepath}' contains hardcoded privileged login(s)/email(s): {hardcoded_logins}"
               if hardcoded_logins else f"File '{filepath}' contains no hardcoded login/email"),
        source=f'security_lock:{filepath}:hardcoded_logins', value=hardcoded_logins or None,
        confidence='HIGH', scope={'sensitive': True} if hardcoded_logins else {}))
    if exception_messages:
        rows = zip(exception_messages, exception_conditions or [''] * len(exception_messages),
            exception_guard_fields or [''] * len(exception_messages), exception_linenos or [0] * len(exception_messages),
            exception_methods or [''] * len(exception_messages))
        for index, (message, condition, guard, lineno, method) in enumerate(rows):
            claim = f'File \'{filepath}\' raises UserError/ValidationError "{message}"'
            if condition:
                claim += f' (condition: {condition})'
            if guard:
                claim += f" (link-guarded on '{guard}')"
            if method:
                claim += f" (in method '{method}()')"
            evidence.append(make_evidence(source_type=EvidenceSourceType.CODE, claim=claim,
                source=f'security_lock:{filepath}:exception:{lineno if lineno else index}', value=message,
                confidence='HIGH', scope={'lineno': lineno} if lineno else {}))
    else:
        evidence.append(make_evidence(source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' raises no UserError/ValidationError with an extractable message",
            source=f'security_lock:{filepath}:exception', value=None, confidence='HIGH', scope={}))
    if required_groups:
        rows = zip(required_groups, required_group_methods or [''] * len(required_groups),
                   required_group_linenos or [0] * len(required_groups),
                   required_group_alt_conditions or [''] * len(required_groups))
        for group, method, lineno, alternative in rows:
            claim = f"File '{filepath}' contains a has_group()/user_has_groups() check of '{group}'"
            if method:
                claim += f" in method '{method}()'"
            claim += '; a literal check alone does not establish a required group or an authorization verdict.'
            if alternative:
                claim += f' Other terms were observed in the enclosing OR: {alternative}.'
            scope = {'method': method, 'lineno': lineno, 'authorization_verdict': 'not_evaluated'}
            evidence.append(make_evidence(source_type=EvidenceSourceType.CODE, claim=claim,
                source=f'security_lock:{filepath}:group:{group}', value=group, confidence='HIGH', scope=scope))
    else:
        evidence.append(make_evidence(source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' contains no extracted literal group check",
            source=f'security_lock:{filepath}:group', value=None, confidence='HIGH', scope={}))
    if dynamic_dispatch_types:
        for pattern in dynamic_dispatch_types:
            evidence.append(make_evidence(source_type=EvidenceSourceType.CODE,
                claim=f"File '{filepath}' uses dynamic dispatch via {pattern}(), not statically classifiable",
                source=f'security_lock:{filepath}:dynamic_dispatch:{pattern}', value=pattern, confidence='LOW', scope={}))
    else:
        evidence.append(make_evidence(source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' uses no dynamic dispatch (getattr/eval/exec)",
            source=f'security_lock:{filepath}:dynamic_dispatch', value=None, confidence='HIGH', scope={}))
    return evidence


def format_security_locks_summary(analysis: Any, code: str, filepath: str) -> str:
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER, format_file_link, format_xml_id_citation
    fileLink = format_file_link(filepath, 1, max(1, len(code.splitlines())))
    lines = [f'Analyse des verrous Python ({fileLink}) [Confiance: {confidence_label(analysis.confidence)}]:']
    if analysis.has_hardcoded_logins:
        lines.append(f'  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilégiés en dur: {analysis.hardcoded_logins}')
    if analysis.required_groups:
        methods = analysis.required_group_methods or [''] * len(analysis.required_groups)
        linenos = analysis.required_group_linenos or [0] * len(analysis.required_groups)
        alternatives = getattr(analysis, 'required_group_alt_conditions', None) or [''] * len(analysis.required_groups)
        lines.append('  - Vérifications de groupes observées : leur présence seule ne prouve ni obligation ni autorisation.')
        rows = _rerank_by_relevance(list(zip(analysis.required_groups, methods, linenos, alternatives)),
                                    text_fn=lambda row: f'{row[0]} {row[1]}', question=get_current_question())
        for group, method, lineno, alternative in rows:
            citation = format_xml_id_citation(group)
            site = format_file_link(filepath, lineno, lineno) if lineno else fileLink
            location = f"dans '{method}()'" if method else 'hors de toute méthode'
            text = f"    * Vérification du groupe '{group}' via has_group()/user_has_groups() {location}. "
            text += 'Lire la condition complète, sa polarité et les autres gardes avant de conclure sur les droits.'
            if alternative:
                text += f' Autres termes du OR observés : {alternative}.'
            lines.append(f'{text} ({citation}) ({site})')
    for name, value, start, end in analysis.static_filters:
        lines.append(f"  - Filtre d'exclusion statique '{name}' ({format_file_link(filepath, start, end)}): {value}")
    if analysis.exception_messages:
        lines.append('  - Security lock messages (UserError/ValidationError):')
        question = get_current_question()
        rows = list(zip(analysis.exception_messages,
            analysis.exception_conditions or [''] * len(analysis.exception_messages),
            analysis.exception_guard_fields or [''] * len(analysis.exception_messages),
            analysis.exception_linenos or [0] * len(analysis.exception_messages),
            getattr(analysis, 'exception_methods', None) or [''] * len(analysis.exception_messages)))
        rows = _rerank_by_relevance(rows, text_fn=lambda row: f'{row[0]} {row[1]}', question=question,
                                   bonus_fn=lambda row: _method_family_bonus(row[4], question))
        for message, condition, guard, lineno, method in rows:
            site = format_file_link(filepath, lineno, lineno) if lineno else fileLink
            suffix = f" (dans '{method}()')" if method else ''
            conditionText = f' (condition : {condition})' if condition else ''
            lines.append(f'    * "{message}"{conditionText}{suffix} ({site})')
            if guard:
                lines.append(f"      [GARDE DE LIEN: si '{guard}' est vide/absent (aucun enregistrement lie), "
                    "cette condition est FAUSSE par court-circuit Python (evaluation de gauche a droite d'un 'and') "
                    '-- la regle ci-dessus NE S’APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]')
    if analysis.has_dynamic_dispatch:
        lines.append(f"  - Incertitude dynamique ({', '.join(analysis.dynamic_dispatch_types)}): revue manuelle recommandée")
    if not analysis.security_warnings and not analysis.exception_messages and not analysis.static_filters:
        lines.append('  - Aucun verrou spécifique ni incertitude dynamique détecté.')
    return '\n'.join(lines)


_EMPTY_BLOCK_LINE = 'Aucun verrou spécifique ni incertitude dynamique détecté.'


def _compact_empty_block(text: str) -> str:
    lines = text.split('\n')
    if len(lines) == 2 and lines[1].strip().lstrip('-').strip() == _EMPTY_BLOCK_LINE:
        match = re.search(r'(\[[^\]]+\]\([^)]+\))', lines[0])
        return f'{match.group(1) if match else lines[0]}: aucun verrou.'
    return text


def assemble_security_lock_blocks(blocks: List[str], budget: int) -> str:
    if not blocks:
        return ''
    if budget <= 0:
        return _truncate_observation('', 0)
    blocks = [_compact_empty_block(block) for block in blocks]
    essentials, exceptions = [], []
    for block in blocks:
        index = block.find(_EXCEPTION_MESSAGES_MARKER)
        essentials.append(block[:index].rstrip('\n') if index != -1 else block)
        exceptions.append(block[index:] if index != -1 else '')
    exceptionSizes = [len(text) for text in exceptions]
    exceptionFloor = min(budget, sum(min(_protected_prefix_end(text), size)
                                    for text, size in zip(exceptions, exceptionSizes) if size))
    essentialSizes = [len(text) for text in essentials]
    essentialBudget = min(budget - exceptionFloor, sum(essentialSizes))
    essentialAlloc = _waterfill_with_protected_minimum(essentialSizes, essentials, essentialBudget)
    remaining = max(0, budget - sum(essentialAlloc))
    exceptionAlloc = _waterfill_with_protected_minimum(exceptionSizes, exceptions, remaining, priority=essentialAlloc)
    parts = []
    for essential, cap, exception, exceptionCap in zip(essentials, essentialAlloc, exceptions, exceptionAlloc):
        if cap <= 0:
            continue
        text = _truncate_observation(essential, cap) if cap < len(essential) else essential
        if exceptionCap > 0:
            text += '\n' + (_truncate_observation(exception, exceptionCap) if exceptionCap < len(exception) else exception)
        parts.append(text)
    return '\n\n'.join(parts)


def extract_method_security_constraints(analysis: Any, lineno: int, end_lineno: int) -> List[str]:
    constraints = []
    alternatives = getattr(analysis, 'required_group_alt_conditions', None) or [''] * len(analysis.required_groups)
    for group, method, groupLine, alternative in zip(analysis.required_groups,
        analysis.required_group_methods, analysis.required_group_linenos, alternatives):
        if groupLine and lineno <= groupLine <= end_lineno:
            location = f"dans '{method}()'" if method else 'à cette ligne'
            text = f"VÉRIFICATION RATTACHÉE AU SITE: groupe '{group}' observé {location}; autorisation non évaluée."
            if alternative:
                text += f' Autres termes du OR observés : {alternative}.'
            constraints.append(text)
    for message, condition, guard, excLine in zip(analysis.exception_messages,
        analysis.exception_conditions or [''] * len(analysis.exception_messages),
        analysis.exception_guard_fields or [''] * len(analysis.exception_messages), analysis.exception_linenos):
        if excLine and lineno <= excLine <= end_lineno:
            text = f'VERROU RATTACHE AU SITE: "{message}"'
            if condition:
                text += f' (condition : {condition})'
            if guard:
                text += f" [GARDE DE LIEN: si '{guard}' est vide/absent, cette condition est FAUSSE "
                text += 'par court-circuit Python -- la regle NE S’APPLIQUE PAS dans ce cas.]'
            constraints.append(text)
    return constraints
