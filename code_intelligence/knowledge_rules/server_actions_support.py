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
    from code_intelligence.knowledge_rules.server_actions import ServerActionCodeAnalysis

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
        messages = build_server_action_messages(analysis, code)
        response = llm.invoke(messages)
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
