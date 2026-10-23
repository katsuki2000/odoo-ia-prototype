"""
code_intelligence/knowledge_rules/server_actions_support.py

Evidence building + LLM interpretation layer for server action static
security analysis
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, List

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence

if TYPE_CHECKING:
    from code_intelligence.rules.server_actions import ServerActionCodeAnalysis

_logger = logging.getLogger(__name__)

# === evidence (ex server_actions/evidence.py) ===============================


def _evidence(action_xml_id: str, suffix: str, claim: str, value: Any) -> Evidence:
    """Single-shape Evidence builder shared by every check below -- all 4
    checks use the same source_type/confidence/scope, only claim/source
    suffix/value vary."""
    return make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=claim,
        source=f"server_action:{action_xml_id}:{suffix}",
        value=value,
        confidence="LOW",
        scope={},
    )


def build_server_action_evidence(
    action_xml_id: str,
    has_sudo: bool,
    trigger_conditions: List[str],
    sudo_call_count: int,
    hardcoded_id_lists: List[List[int]],
    dynamic_dispatch_patterns: List[str],
    group_checks: List[str],
) -> List[Evidence]:
    """Build structured Evidence for server action security checks -- one
    positive Evidence per finding, or a single negative Evidence per check
    category when nothing was found (never silent about an absence)."""
    evidence: List[Evidence] = []

    if has_sudo:
        cond = f", conditioned by: {'; '.join(trigger_conditions)}" if trigger_conditions else ""
        evidence.append(_evidence(
            action_xml_id, "sudo",
            f"Server action '{action_xml_id}' calls sudo() ({sudo_call_count} call(s)), "
            f"bypassing ir.rule and ACL checks{cond}",
            sudo_call_count,
        ))
    else:
        evidence.append(_evidence(action_xml_id, "sudo", f"Server action '{action_xml_id}' does not call sudo()", None))

    if hardcoded_id_lists:
        for ids in hardcoded_id_lists:
            evidence.append(_evidence(
                action_xml_id, "hardcoded_ids",
                f"Server action '{action_xml_id}' contains a hardcoded ID list: {ids}",
                ids,
            ))
    else:
        evidence.append(_evidence(
            action_xml_id, "hardcoded_ids", f"Server action '{action_xml_id}' contains no hardcoded ID list", None,
        ))

    if dynamic_dispatch_patterns:
        for pattern_name in dynamic_dispatch_patterns:
            evidence.append(_evidence(
                action_xml_id, f"dynamic_dispatch:{pattern_name}",
                f"Server action '{action_xml_id}' uses dynamic dispatch via {pattern_name}(), not statically classifiable",
                pattern_name,
            ))
    else:
        evidence.append(_evidence(
            action_xml_id, "dynamic_dispatch",
            f"Server action '{action_xml_id}' uses no dynamic dispatch (getattr/eval/exec)", None,
        ))

    if group_checks:
        evidence.append(_evidence(
            action_xml_id, "group_checks",
            f"Server action '{action_xml_id}' checks group membership via has_group() for: "
            f"{', '.join(sorted(group_checks))}",
            sorted(group_checks),
        ))
    else:
        evidence.append(_evidence(
            action_xml_id, "group_checks", f"Server action '{action_xml_id}' contains no has_group() check", None,
        ))

    return evidence


# === prompts =================================

_SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de sécurité pour du code Odoo ir.actions.server (server actions). "
    "Un premier passage automatique (regex) a déjà détecté des patterns de sécurité dans ce "
    "code -- ta tâche est UNIQUEMENT d'interpréter et résumer en une phrase ce que fait "
    "concrètement ce code du point de vue métier/sécurité, et d'indiquer ta confiance dans "
    "cette interprétation. Réponds STRICTEMENT en JSON, sans aucun texte avant ou après, "
    'au format exact: {"summary": "...", "confidence": "high"|"medium"|"low"}. '
    "N'utilise JAMAIS une autre valeur de confidence que high, medium, ou low."
)


def _build_interpretation_prompt(analysis: "ServerActionCodeAnalysis", code: str) -> str:
    """Build the bounded user prompt for server action security interpretation."""
    detected = "\n".join(f"- {w}" for w in analysis.security_warnings)
    return (
        f"Code de l'action serveur '{analysis.action_xml_id}':\n"
        f"```python\n{code}\n```\n\n"
        f"Patterns déjà détectés par analyse statique (regex):\n{detected}\n\n"
        "Résume en une phrase claire ce que fait ce code du point de vue métier/sécurité, "
        "et indique ta confiance dans cette interprétation."
    )


def build_server_action_messages(analysis: "ServerActionCodeAnalysis", code: str) -> List[BaseMessage]:
    """Construct the full message list for server action LLM interpretation."""
    return [
        SystemMessage(content=_SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=_build_interpretation_prompt(analysis, code)),
    ]


# === llm =========================================

_LLM_CONFIDENCE_CLOSED_SET = {"high", "medium", "low"}


def interpret_server_action_with_llm(
    analysis: "ServerActionCodeAnalysis",
    code: str,
    llm,
) -> "ServerActionCodeAnalysis":
    """Bounded LLM interpretation complementing static regex analysis."""
    if not analysis.security_warnings or llm is None:
        return analysis

    try:
        from core.llm.llm_client import invoke_with_rate_limit

        messages = build_server_action_messages(analysis, code)

        def _rebuild():
            from core.llm.llm_client import get_chat_llm
            return get_chat_llm(temperature=0.0, max_retries=0)

        response, _wait = invoke_with_rate_limit(llm, messages, max_retries=5, rebuild_llm=_rebuild)
        raw = (response.content or "").strip()
    except Exception as e:
        _logger.warning("LLM interpretation call failed for action=%r: %s", analysis.action_xml_id, e)
        return analysis

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _logger.warning("LLM interpretation returned non-JSON response for action=%r: %r", analysis.action_xml_id, raw)
        return analysis

    if not isinstance(parsed, dict):
        return analysis

    summary = parsed.get("summary")
    confidence = parsed.get("confidence")

    if confidence not in _LLM_CONFIDENCE_CLOSED_SET or not summary or not isinstance(summary, str):
        return analysis

    analysis.llm_summary = summary
    analysis.llm_confidence = confidence

    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    llm_tag = f"{SENSITIVE_BYPASS_MARKER} " if (analysis.has_sudo or analysis.has_hardcoded_ids) else ""
    analysis.summary_text += (
        f"\n  -> {llm_tag}Interprétation LLM [confiance: {confidence.upper()}, distincte de la "
        f"confiance statique ci-dessus]: {summary}"
    )

    return analysis


__all__ = [
    "build_server_action_evidence",
    "_SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT",
    "_build_interpretation_prompt",
    "build_server_action_messages",
    "_LLM_CONFIDENCE_CLOSED_SET",
    "interpret_server_action_with_llm",
]

# ── Server Actions Analysis ──────────────────────────────────────────────

import re
from dataclasses import dataclass, field
from typing import List, Optional
import logging

from core.evidence.evidence import Evidence
from core.output import confidence_label
from code_intelligence.utils import (
    SENSITIVE_BYPASS_MARKER,
    format_xml_id_citation,
    format_xml_id_citations,
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
_DYNAMIC_DISPATCH_PATTERNS = ((_GETATTR_PATTERN, "getattr"), (_EVAL_PATTERN, "eval"), (_EXEC_PATTERN, "exec"))


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


def _cond_clause(trigger_conditions: List[str]) -> str:
    """Shared 'Conditionné par: ...' suffix -- was duplicated verbatim at
    the sudo() and hardcoded-IDs warning sites."""
    return f" Conditionné par: {'; '.join(trigger_conditions)}." if trigger_conditions else ""


def _empty_code_result(action_xml_id, action_type, action_name, user_id, interval_number, interval_type) -> ServerActionCodeAnalysis:
    result = ServerActionCodeAnalysis(
        action_xml_id=action_xml_id, action_type=action_type, action_name=action_name,
        user_id=user_id, interval_number=interval_number, interval_type=interval_type,
    )
    if action_type == "cron":
        interval_str = f", intervalle: {interval_number} {interval_type}" if interval_type else ""
        user_str = f", utilisateur: {user_id}" if user_id else ""
        result.summary_text = f"Action planifiée (ir.cron) '{action_xml_id}'{interval_str}{user_str}: Aucun code à analyser."
    else:
        result.summary_text = f"Action '{action_xml_id}': No code to analyze."
    result.evidence = _build_server_action_evidence(
        action_xml_id, has_sudo=False, trigger_conditions=[], sudo_call_count=0,
        hardcoded_id_lists=[], dynamic_dispatch_patterns=[], group_checks=[],
    )
    return result


def _detect_patterns(code: str, code_lines: List[str], action_xml_id: str, result: ServerActionCodeAnalysis) -> int:
    """Run the 4 regex-based detectors, mutating `result` in place, and
    return the raw sudo() match count (needed separately for Evidence)."""
    sudo_matches = list(_SUDO_PATTERN.finditer(code))
    if sudo_matches:
        result.has_sudo = True
        for m in sudo_matches:
            cond = _find_enclosing_if_condition(code_lines, _line_number_of(code, m.start()))
            if cond and cond not in result.trigger_conditions:
                result.trigger_conditions.append(cond)
        result.security_warnings.append(
            f" SUDO: L'action '{action_xml_id}' utilise sudo() ({len(sudo_matches)} appels). "
            f"Cela contourne les règles d'accès (ir.rule) et les ACL."
            f"{_cond_clause(result.trigger_conditions)} [Confiance: {confidence_label('low')} - logique stockée en données XML]"
        )

    result.has_group_checks = list(set(_HAS_GROUP_PATTERN.findall(code)))

    for match in _HARDCODED_ID_LIST_PATTERN.finditer(code):
        try:
            ids = [int(x.strip()) for x in match.group(1).split(",") if x.strip()]
        except ValueError:
            continue
        if not ids:
            continue
        result.has_hardcoded_ids = True
        result.hardcoded_id_lists.append(ids)
        result.security_warnings.append(
            f" IDs EN DUR: L'action '{action_xml_id}' contient une liste d'IDs "
            f"codés en dur: {ids}. Ces enregistrements bénéficient d'un traitement "
            f"spécial non documenté dans les modèles Python."
            f"{_cond_clause(result.trigger_conditions)} [Confiance: {confidence_label('low')} - logique stockée en données XML]"
        )

    for pattern, name in _DYNAMIC_DISPATCH_PATTERNS:
        if pattern.search(code):
            result.has_dynamic_dispatch = True
            result.dynamic_dispatch_patterns.append(name)
            result.security_warnings.append(
                f" DISPATCH DYNAMIQUE: L'action '{action_xml_id}' utilise {name}(). "
                f"Impossible de déterminer statiquement le comportement exact. "
                f"[Confiance: {confidence_label('low')} - nécessite revue manuelle]"
            )

    return len(sudo_matches)


def _build_summary_lines(code: str, action_xml_id: str, action_type: str, action_name: str,
                          user_id: str, interval_number: int, interval_type: str,
                          result: ServerActionCodeAnalysis) -> List[str]:
    citation = format_xml_id_citation(action_xml_id)
    if action_type == "cron":
        name_info = f" '{action_name}'" if action_name else ""
        lines = [
            f"Action planifiée (ir.cron){name_info} '{action_xml_id}' "
            f"({citation}) [Confiance: {confidence_label('low')} - logique en données XML, modifiable à l'exécution]:",
            f"  - Type: Action récurrente planifiée (ir.cron)",
        ]
        if interval_type:
            lines.append(f"  - Périodicité / Intervalle: toutes les {interval_number} {interval_type}")
        if user_id:
            user_desc = " (droits superutilisateur/root)" if user_id in ("base.user_root", "user_root") else ""
            lines.append(f"  - Utilisateur d'exécution (droits): {user_id}{user_desc}")
        if code.strip():
            lines.append(f"  - Code Python exécuté: {code.strip()}")
    else:
        lines = [
            f"Analyse du code de l'action serveur '{action_xml_id}' "
            f"({citation}) [Confiance: {confidence_label('low')} - logique en données XML, modifiable à l'exécution]:"
        ]

    if result.has_sudo:
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} SUDO détecté: Contournement des droits d'accès via sudo()")
    for id_list in result.hardcoded_id_lists:
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} IDs en dur: {id_list} → traitement privilégié non documenté")
    if result.trigger_conditions:
        lines.append(f"  - Condition(s) de déclenchement: " + "; ".join(result.trigger_conditions))
    if result.has_group_checks:
        lines.append(
            f"  - Vérifications de groupes: {', '.join(result.has_group_checks)} "
            f"({format_xml_id_citations(result.has_group_checks)})"
        )
    if result.has_dynamic_dispatch:
        lines.append(
            f"  - Dispatch dynamique: {', '.join(result.dynamic_dispatch_patterns)} "
            f"→ comportement non classifiable statiquement"
        )
    if not result.security_warnings and action_type != "cron":
        lines.append("  - Aucun pattern de sécurité détecté dans le code.")

    return lines


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
    if not code or not code.strip():
        return _empty_code_result(action_xml_id, action_type, action_name, user_id, interval_number, interval_type)

    result = ServerActionCodeAnalysis(
        action_xml_id=action_xml_id, action_type=action_type, action_name=action_name,
        user_id=user_id, interval_number=interval_number, interval_type=interval_type,
    )
    code_lines = code.splitlines()
    sudo_call_count = _detect_patterns(code, code_lines, action_xml_id, result)

    lines = _build_summary_lines(code, action_xml_id, action_type, action_name, user_id, interval_number, interval_type, result)

    result.evidence = _build_server_action_evidence(
        action_xml_id,
        has_sudo=result.has_sudo,
        trigger_conditions=result.trigger_conditions,
        sudo_call_count=sudo_call_count,
        hardcoded_id_lists=result.hardcoded_id_lists,
        dynamic_dispatch_patterns=result.dynamic_dispatch_patterns,
        group_checks=result.has_group_checks,
    )
    result.summary_text = "\n".join(lines)
    return result


__all__ = [
    "ServerActionCodeAnalysis",
    "analyze_server_action_code",
    "build_server_action_evidence",
    "interpret_server_action_with_llm",
    "_SUDO_PATTERN",
    "_HARDCODED_ID_LIST_PATTERN",
    "_HAS_GROUP_PATTERN",
    "_GETATTR_PATTERN",
    "_EVAL_PATTERN",
    "_EXEC_PATTERN",
]
