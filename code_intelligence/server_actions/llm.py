"""LLM interpretation layer for server action security findings."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.server_actions.analyzer import ServerActionCodeAnalysis

_logger = logging.getLogger(__name__)

_LLM_CONFIDENCE_CLOSED_SET = {"high", "medium", "low"}

from .prompts import (
    _SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT,
    _build_interpretation_prompt,
    build_server_action_messages,
)


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
