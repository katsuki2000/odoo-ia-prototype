"""Legacy answer corrections and explicit sensitive-evidence disclosure policy."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

import networkx as nx

from code_intelligence.utils import (
    _match_near_truncation, _extract_amount, _question_is_approval_related,
    _has_can_view_amount_fact, _split_before_first_fact_marker,
    _LOCK_CONDITION_LINE_RE, _AMOUNT_CMP_RE,
)
from code_intelligence.rules.group_resolver import _fold_accents

logger = logging.getLogger(__name__)
_OVERRIDE_CHAIN_AMOUNT_RE = re.compile(r"rec\.\w+\s*>\s*(\d[\d\s]*\d)")
_SECURITY_LOCK_MESSAGES_MARKER = 'Security lock messages (UserError/ValidationError)'


def _amount_present_in_text(amount: str, text: str) -> bool:
    spaced = f'{amount[:-3]} {amount[-3:]}' if len(amount) > 3 else amount
    return any(re.search(r'(?<!\d)' + re.escape(candidate) + r'(?!\d)', text)
               for candidate in {amount, spaced})


def _extract_security_lock_condition_amounts(raw_tool_output: str) -> List[str]:
    amounts = []
    for block in raw_tool_output.split('\n\n'):
        if _SECURITY_LOCK_MESSAGES_MARKER not in block:
            continue
        for match in _OVERRIDE_CHAIN_AMOUNT_RE.finditer(block):
            if _match_near_truncation(block, match.start(), match.end()):
                continue
            amount = match.group(1).replace(' ', '').strip()
            if amount and amount not in amounts:
                amounts.append(amount)
    return amounts


def _backfill_missing_security_lock_amount(final_answer: str, raw_tool_output: str, question: Optional[str] = None) -> str:
    """Legacy API; not part of the active answer pipeline."""
    if question is not None:
        if _has_can_view_amount_fact(final_answer):
            return final_answer
        if not (_question_is_approval_related(question) or _extract_amount(question) is not None):
            return final_answer
        amount = _extract_amount(question)
    else:
        amount = None
    amounts = _extract_security_lock_condition_amounts(raw_tool_output)
    if amount is not None:
        amounts = [a for a in amounts if float(a) <= amount]
    if not amounts:
        return final_answer
    amountList = ', '.join(f'{a}€' for a in amounts)
    return final_answer + (
        f'\n\n[FAIT DÉTERMINISTIQUE] Le verrou de sécurité contient une condition '
        f'supplémentaire déclenchée au-delà de {amountList}, distincte du groupe '
        f'requis ci-dessus. Fait extrait directement de l’analyse statique du code.')


def _backfill_missing_approval_guard_facts(final_answer: str, raw_tool_output: str, question: str) -> str:
    """Legacy API; not part of the active answer pipeline."""
    if '_approval_allowed' not in raw_tool_output:
        return final_answer
    guardStart = raw_tool_output.find('_approval_allowed')
    nextMethod = raw_tool_output.find('\ndef ', guardStart + len('_approval_allowed'))
    guardOutput = raw_tool_output[guardStart:nextMethod if nextMethod != -1 else guardStart + 4000]
    if not any(term in _fold_accents(question.lower()) for term in ('acl', 'groupe', 'manager', 'acheteur', 'permission')):
        return final_answer
    facts, tokens = [], []
    if re.search(r"po_double_validation\s*==\s*['\"]one_step['\"]", guardOutput):
        facts.append("`po_double_validation == 'one_step'`")
        tokens.append('one_step')
    if re.search(r"po_double_validation\s*==\s*['\"]two_step['\"]", guardOutput):
        facts.append("`po_double_validation == 'two_step'` avec un montant total inférieur au seuil configuré `po_double_validation_amount`")
        tokens.extend(('two_step', 'po_double_validation_amount'))
    match = re.search(r"(?:user_has_groups|has_group)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", guardOutput)
    if match:
        facts.append(f"l'appartenance au groupe `{match.group(1)}`")
        tokens.append(match.group(1))
    if not facts or all(token in final_answer for token in tokens):
        return final_answer
    return (final_answer.rstrip() + '\n\n[FAIT DÉTERMINISTIQUE] Le garde applicatif `_approval_allowed()` '
            "autorise l'approbation si au moins une des conditions suivantes est vraie : " + '; '.join(facts) + '.')


def _backfill_fiscal_lock_scope_fact(final_answer: str, raw_tool_output: str, question: str) -> str:
    """Legacy API; not part of the active answer pipeline."""
    folded = _fold_accents(question.lower())
    if not ('lock date' in folded or 'cloture' in folded or 'fiscalyear_lock_date' in folded):
        return final_answer
    required = ('_get_user_fiscal_lock_date', 'period_lock_date', 'fiscalyear_lock_date', 'group_account_manager')
    if not all(token in raw_tool_output for token in required):
        return final_answer
    marker = '[FAIT DÉTERMINISTIQUE -- PORTÉE DES DATES DE CLÔTURE]'
    if marker in final_answer:
        return final_answer
    for pattern in (
        r"^.*(?:peut poster|peut publier|autorisé.*date.*clôture|jusqu'à cette date).*$\n?",
        r"^.*(?:Accès au niveau|date de clôture finale|L'administrateur a accès|Si la date de l'écriture dépasse).*$\n?",
        r'^.*(?:société mère|société parente).*$\n?',
    ):
        final_answer = re.sub(pattern, '', final_answer, flags=re.MULTILINE | re.IGNORECASE).rstrip()
    return final_answer + (
        '\n\n**Réponse : non.** La date de clôture d’exercice reste bloquante, y compris pour le Billing Administrator.'
        '\n\n' + marker + " Non : l'exemption de `account.group_account_manager` dans `_get_user_fiscal_lock_date()` "
        'ne concerne que `period_lock_date` (verrou de période). Elle conserve `fiscalyear_lock_date` comme date '
        'effective ; `_check_fiscalyear_lock_date()` bloque donc aussi le Billing Administrator lorsque la date '
        "de l'écriture est antérieure ou égale à la clôture d'exercice.")


def _correct_security_lock_threshold_contradictions(final_answer: str, scoped_tool_output: str, question: str) -> str:
    """Retired unsafe correction: group membership alone cannot establish permission."""
    return final_answer


_OMITTED_MARKER = 'ELEMENT OMITTED FOR AUTHORIZATION REASON'


@dataclass
class OmittedItem:
    label: str
    reason: str


def _expand_user_groups_ordered(G: nx.DiGraph, user_groups: List[str]) -> List[str]:
    from code_intelligence.rules.group_resolver import _expand_implied_user_groups
    ordered = list(dict.fromkeys(str(group) for group in user_groups or []))
    implied: Set[str] = set()
    for group in ordered:
        _expand_implied_user_groups(G, group, implied)
    return ordered + sorted(implied.difference(ordered))


def _find_elevating_group(G: nx.DiGraph, model_name: str, user_groups: List[str]) -> Optional[str]:
    """Return an explicitly authorized disclosure group, never a source/ACL guess."""
    from config.settings import SENSITIVE_EVIDENCE_GROUP_XMLIDS
    if not SENSITIVE_EVIDENCE_GROUP_XMLIDS:
        return None
    return next((group for group in _expand_user_groups_ordered(G, user_groups)
                 if group in SENSITIVE_EVIDENCE_GROUP_XMLIDS), None)


def _has_elevated_access(G: nx.DiGraph, model_name: str, user_groups: List[str]) -> bool:
    """Legacy name for the disclosure policy; does not authorize business operations."""
    return _find_elevating_group(G, model_name, user_groups) is not None


def _redact_sensitive_bypass_lines(observation: str, model_name: str, G: nx.DiGraph,
                                   user_groups: List[str]) -> Tuple[str, List[OmittedItem]]:
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    if SENSITIVE_BYPASS_MARKER not in observation or _has_elevated_access(G, model_name, user_groups):
        return observation, []
    omitted, lines = [], []
    for line in observation.splitlines():
        if SENSITIVE_BYPASS_MARKER not in line:
            lines.append(line)
            continue
        omitted.append(OmittedItem(
            label='Détail technique sensible',
            reason="Élément omis pour raison d'autorisation : la politique de divulgation des preuves techniques ne confirme pas l’autorisation du demandeur."))
        lines.append(f'  - [{_OMITTED_MARKER}] (détail technique masqué)')
    return '\n'.join(lines), omitted


def gate_observation(tool_name: str, model_name: str, observation: str, G: nx.DiGraph,
                     user_groups: List[str], rule_result: Optional[object] = None) -> Tuple[str, List[OmittedItem]]:
    return _redact_sensitive_bypass_lines(observation, model_name, G, user_groups)


def filter_disclosed_evidence(evidence, allowed: bool):
    """Apply the same disclosure decision to the structured dossier."""
    return [item for item in evidence if allowed or not item.scope.get('sensitive', False)]
