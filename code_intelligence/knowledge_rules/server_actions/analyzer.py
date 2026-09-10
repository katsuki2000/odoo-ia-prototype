"""
Static analysis of ir.actions.server 'code' fields.
Detects security-relevant patterns:
  - sudo() calls (privilege escalation)
  - has_group() checks (group-based conditional logic)
  - Hardcoded ID lists (partner/user IDs, bypasses)
  - eval/exec/getattr (dynamic dispatch)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional
import logging

from core.evidence.evidence import Evidence
from core.output.confidence_tags import confidence_label
from code_intelligence.knowledge_rules.server_actions.evidence import build_server_action_evidence
from code_intelligence.knowledge_rules.server_actions.llm import (
    interpret_server_action_with_llm,
    _build_interpretation_prompt,
    _SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT,
    _LLM_CONFIDENCE_CLOSED_SET,
)

_logger = logging.getLogger(__name__)

_build_server_action_evidence = build_server_action_evidence


@dataclass
class ServerActionCodeAnalysis:
    """Result of analyzing an ir.actions.server code field."""
    action_xml_id: str
    action_type: str = "server_action"
    action_name: str = ""
    user_id: str = ""
    interval_number: int = 1
    interval_type: str = ""
    has_sudo: bool = False
    has_hardcoded_ids: bool = False
    hardcoded_id_lists: List[List[int]] = field(default_factory=list)
    has_group_checks: List[str] = field(default_factory=list)
    has_dynamic_dispatch: bool = False
    dynamic_dispatch_patterns: List[str] = field(default_factory=list)
    security_warnings: List[str] = field(default_factory=list)
    confidence: str = "low"
    summary_text: str = ""
    llm_summary: Optional[str] = None
    llm_confidence: Optional[str] = None
    trigger_conditions: List[str] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)


_SUDO_PATTERN = re.compile(r"\.sudo\s*\(")
_HAS_GROUP_PATTERN = re.compile(r"\.has_group\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_HARDCODED_ID_LIST_PATTERN = re.compile(r"\b[A-Z_]+\s*=\s*\[(\s*\d+(?:\s*,\s*\d+)*\s*)\]")
_GETATTR_PATTERN = re.compile(r"\bgetattr\s*\(")
_EVAL_PATTERN = re.compile(r"\beval\s*\(")
_EXEC_PATTERN = re.compile(r"\bexec\s*\(")
_IF_LINE_PATTERN = re.compile(r"^if\s+(.+):\s*$")


def _line_number_of(code: str, char_offset: int) -> int:
    return code.count("\n", 0, char_offset) + 1


def _find_enclosing_if_condition(code_lines: List[str], line_no: int) -> Optional[str]:
    """Scan backward from line_no for nearest enclosing if condition."""
    if line_no - 1 >= len(code_lines) or line_no - 1 < 0:
        return None
    target_indent = len(code_lines[line_no - 1]) - len(code_lines[line_no - 1].lstrip())
    for i in range(line_no - 2, -1, -1):
        line = code_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < target_indent:
            match = _IF_LINE_PATTERN.match(stripped)
            if match:
                return match.group(1).strip()
            target_indent = indent
            if indent == 0:
                return None
    return None


def analyze_server_action_code(
    code: str,
    action_xml_id: str,
    action_type: str = "server_action",
    action_name: str = "",
    user_id: str = "",
    interval_number: int = 1,
    interval_type: str = "",
) -> ServerActionCodeAnalysis:
    """Analyze an ir.actions.server or ir.cron code field for security patterns."""
    result = ServerActionCodeAnalysis(
        action_xml_id=action_xml_id,
        action_type=action_type,
        action_name=action_name,
        user_id=user_id,
        interval_number=interval_number,
        interval_type=interval_type,
    )

    if not code or not code.strip():
        if action_type == "cron":
            interval_str = f", intervalle: {interval_number} {interval_type}" if interval_type else ""
            user_str = f", utilisateur: {user_id}" if user_id else ""
            result.summary_text = f"Action planifiée (ir.cron) '{action_xml_id}'{interval_str}{user_str}: Aucun code à analyser."
        else:
            result.summary_text = f"Action '{action_xml_id}': No code to analyze."
        result.evidence = _build_server_action_evidence(
            action_xml_id,
            has_sudo=False,
            trigger_conditions=[],
            sudo_call_count=0,
            hardcoded_id_lists=[],
            dynamic_dispatch_patterns=[],
            group_checks=[],
        )
        return result

    code_lines = code.splitlines()

    # 1. Detect sudo() calls
    sudo_matches = list(_SUDO_PATTERN.finditer(code))
    if sudo_matches:
        result.has_sudo = True
        for m in sudo_matches:
            line_no = _line_number_of(code, m.start())
            cond = _find_enclosing_if_condition(code_lines, line_no)
            if cond and cond not in result.trigger_conditions:
                result.trigger_conditions.append(cond)
        cond_clause = f" Conditionné par: {'; '.join(result.trigger_conditions)}." if result.trigger_conditions else ""
        result.security_warnings.append(
            f" SUDO: L'action '{action_xml_id}' utilise sudo() ({len(sudo_matches)} appels). "
            f"Cela contourne les règles d'accès (ir.rule) et les ACL."
            f"{cond_clause} [Confiance: {confidence_label('low')} - logique stockée en données XML]"
        )

    # 2. Detect has_group() checks
    group_matches = _HAS_GROUP_PATTERN.findall(code)
    if group_matches:
        result.has_group_checks = list(set(group_matches))

    # 3. Detect hardcoded ID lists
    id_list_matches = _HARDCODED_ID_LIST_PATTERN.finditer(code)
    for match in id_list_matches:
        raw_ids = match.group(1)
        try:
            ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
            if ids:
                result.has_hardcoded_ids = True
                result.hardcoded_id_lists.append(ids)
                cond_clause = f" Conditionné par: {'; '.join(result.trigger_conditions)}." if result.trigger_conditions else ""
                result.security_warnings.append(
                    f" IDs EN DUR: L'action '{action_xml_id}' contient une liste d'IDs "
                    f"codés en dur: {ids}. Ces enregistrements bénéficient d'un traitement "
                    f"spécial non documenté dans les modèles Python."
                    f"{cond_clause} [Confiance: {confidence_label('low')} - logique stockée en données XML]"
                )
        except ValueError:
            pass

    # 4. Detect dynamic dispatch
    for pattern, name in [
        (_GETATTR_PATTERN, "getattr"),
        (_EVAL_PATTERN, "eval"),
        (_EXEC_PATTERN, "exec"),
    ]:
        if pattern.search(code):
            result.has_dynamic_dispatch = True
            result.dynamic_dispatch_patterns.append(name)
            result.security_warnings.append(
                f" DISPATCH DYNAMIQUE: L'action '{action_xml_id}' utilise {name}(). "
                f"Impossible de déterminer statiquement le comportement exact. "
                f"[Confiance: {confidence_label('low')} - nécessite revue manuelle]"
            )

    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER, format_xml_id_citation
    _action_citation = format_xml_id_citation(action_xml_id)
    if action_type == "cron":
        name_info = f" '{action_name}'" if action_name else ""
        lines = [
            f"Action planifiée (ir.cron){name_info} '{action_xml_id}' "
            f"({_action_citation}) [Confiance: {confidence_label('low')} - logique en données XML, modifiable à l'exécution]:",
            f"  - Type: Action récurrente planifiée (ir.cron)",
        ]
        if interval_type:
            lines.append(f"  - Périodicité / Intervalle: toutes les {interval_number} {interval_type}")
        if user_id:
            user_desc = " (droits superutilisateur/root)" if user_id in ("base.user_root", "user_root") else ""
            lines.append(f"  - Utilisateur d'exécution (droits): {user_id}{user_desc}")
        if code and code.strip():
            lines.append(f"  - Code Python exécuté: {code.strip()}")
    else:
        lines = [
            f"Analyse du code de l'action serveur '{action_xml_id}' "
            f"({_action_citation}) [Confiance: {confidence_label('low')} - logique en données XML, modifiable à l'exécution]:"
        ]

    if result.has_sudo:
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} SUDO détecté: Contournement des droits d'accès via sudo()")

    if result.has_hardcoded_ids:
        for id_list in result.hardcoded_id_lists:
            lines.append(f"  - {SENSITIVE_BYPASS_MARKER} IDs en dur: {id_list} → traitement privilégié non documenté")

    if result.trigger_conditions:
        lines.append(f"  - Condition(s) de déclenchement: " + "; ".join(result.trigger_conditions))

    if result.has_group_checks:
        from code_intelligence.utils import format_xml_id_citations
        _group_citations = format_xml_id_citations(result.has_group_checks)
        lines.append(f"  - Vérifications de groupes: {', '.join(result.has_group_checks)} ({_group_citations})")

    if result.has_dynamic_dispatch:
        lines.append(
            f"  - Dispatch dynamique: {', '.join(result.dynamic_dispatch_patterns)} "
            f"→ comportement non classifiable statiquement"
        )

    if not result.security_warnings and action_type != "cron":
        lines.append("  - Aucun pattern de sécurité détecté dans le code.")

    result.evidence = _build_server_action_evidence(
        action_xml_id,
        has_sudo=result.has_sudo,
        trigger_conditions=result.trigger_conditions,
        sudo_call_count=len(sudo_matches),
        hardcoded_id_lists=result.hardcoded_id_lists,
        dynamic_dispatch_patterns=result.dynamic_dispatch_patterns,
        group_checks=result.has_group_checks,
    )

    result.summary_text = "\n".join(lines)
    return result
