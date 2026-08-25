from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

import networkx as nx

_OMITTED_MARKER = "ELEMENT OMITTED FOR AUTHORIZATION REASON"
_HAS_GROUP_SOURCE_PATTERN = re.compile(r"\.has_group\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")



@dataclass
class OmittedItem:
    """
    A single element withheld from the demandeur for authorization reasons.
    `reason` is always explicit and human-readable -- never a bare status
    code -- so it can be surfaced to the user as-is, distinct from a
    confidence/coverage score.
    """
    label: str
    reason: str


def _extract_has_group_xmlids_from_source(G: nx.DiGraph, model_name: str) -> Set[str]:
    from code_intelligence.ci_agent_tools import find_model_source_filepaths

    filepaths = find_model_source_filepaths(G, model_name)
    found: Set[str] = set()
    for fp in filepaths:
        p = Path(fp)
        if not p.exists():
            continue
        try:
            code = p.read_text(encoding="utf-8")
        except Exception:
            continue
        found.update(_HAS_GROUP_SOURCE_PATTERN.findall(code))
    return found


def _expand_user_groups_ordered(G: nx.DiGraph, user_groups: List[str]) -> List[str]:
    if not user_groups:
        return []

    from code_intelligence.deterministic_tools import _expand_implied_user_groups

    explicit_seen: Set[str] = set()
    ordered_groups: List[str] = []
    for ug in user_groups:
        s = str(ug)
        if s not in explicit_seen:
            explicit_seen.add(s)
            ordered_groups.append(s)

    implied_set: Set[str] = set()
    for g in ordered_groups:
        _expand_implied_user_groups(G, g, implied_set)

    implied_sorted: List[str] = sorted(g for g in implied_set if g not in explicit_seen)
    return ordered_groups + implied_sorted


def _has_elevated_access(G: nx.DiGraph, model_name: str, user_groups: List[str]) -> bool:
    if not model_name:
        return False

    from code_intelligence.deterministic_tools import (
        _eval_single_permission,
        resolve_group_identifier,
    )

    expanded_groups = _expand_user_groups_ordered(G, user_groups)

    source_has_group_ids = _extract_has_group_xmlids_from_source(G, model_name)
    if source_has_group_ids:
        candidate_groups = list(source_has_group_ids)
        return any(
            resolve_group_identifier(G, str(ug), candidate_groups) is not None
            for ug in expanded_groups
        )

    write_groups, write_auth, _ = _eval_single_permission(G, model_name, "write")
    unlink_groups, unlink_auth, _ = _eval_single_permission(G, model_name, "unlink")

    if write_auth or unlink_auth:
        # ACL grants the right to all authenticated users -- not gated.
        return True

    candidate_groups = list(write_groups | unlink_groups)
    if not candidate_groups:
        return False

    return any(
        resolve_group_identifier(G, str(ug), candidate_groups) is not None
        for ug in expanded_groups
    )


def _find_elevating_group(G: nx.DiGraph, model_name: str, user_groups: List[str]) -> Optional[str]:
    if not model_name or not user_groups:
        return None

    from code_intelligence.deterministic_tools import (
        _eval_single_permission,
        resolve_group_identifier,
    )

    expanded_groups = _expand_user_groups_ordered(G, user_groups)

    source_has_group_ids = _extract_has_group_xmlids_from_source(G, model_name)
    if source_has_group_ids:
        candidate_groups = list(source_has_group_ids)
        for ug in expanded_groups:
            resolved = resolve_group_identifier(G, str(ug), candidate_groups)
            if resolved is not None:
                return resolved
        return None

    write_groups, write_auth, _ = _eval_single_permission(G, model_name, "write")
    unlink_groups, unlink_auth, _ = _eval_single_permission(G, model_name, "unlink")
    if write_auth or unlink_auth:
        return None  # Elevated for everyone -- not a distinguishing fact.

    candidate_groups = list(write_groups | unlink_groups)
    if not candidate_groups:
        return None
    for ug in expanded_groups:
        resolved = resolve_group_identifier(G, str(ug), candidate_groups)
        if resolved is not None:
            return resolved
    return None


def _redact_sensitive_bypass_lines(
    observation: str,
    model_name: str,
    G: nx.DiGraph,
    user_groups: List[str],
) -> Tuple[str, List[OmittedItem]]:
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER

    if SENSITIVE_BYPASS_MARKER not in observation:
        return observation, []
    if _has_elevated_access(G, model_name, user_groups):
        return observation, []

    omitted: List[OmittedItem] = []
    out_lines: List[str] = []
    for line in observation.splitlines():
        if SENSITIVE_BYPASS_MARKER not in line:
            out_lines.append(line)
            continue

        detail = line.split(SENSITIVE_BYPASS_MARKER, 1)[1].strip(" -")
        label = (detail.split(":")[0].strip() if detail else "") or "mécanisme de contournement de sécurité"
        model_suffix = f" ({model_name})" if model_name else ""
        omitted.append(OmittedItem(
            label=f"{label}{model_suffix}",
            reason=(
                f"{_OMITTED_MARKER} : cette ligne décrit un mécanisme de contournement de "
                "sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté "
                "hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès "
                f"élevé sur '{model_name}'." if model_name else
                f"{_OMITTED_MARKER} : cette ligne décrit un mécanisme de contournement de sécurité."
            ),
        ))
        out_lines.append(f"  - [{_OMITTED_MARKER}] (détail masqué -- mécanisme de contournement de sécurité)")

    return "\n".join(out_lines), omitted


def gate_observation(
    tool_name: str,
    model_name: str,
    observation: str,
    G: nx.DiGraph,
    user_groups: List[str],
    rule_result: Optional["object"] = None,
) -> Tuple[str, List[OmittedItem]]:

    omitted_items: List[OmittedItem] = []

    observation, bypass_omitted = _redact_sensitive_bypass_lines(observation, model_name, G, user_groups)
    omitted_items.extend(bypass_omitted)

    return observation, omitted_items
