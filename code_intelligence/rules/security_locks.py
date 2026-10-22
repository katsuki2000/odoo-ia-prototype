"""Explicit sensitive-evidence disclosure policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

import networkx as nx

logger = logging.getLogger(__name__)


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
