"""
code_intelligence/tests/test_j8_llm_server_action_interpretation.py

"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from code_intelligence.knowledge_rules.server_actions.analyzer import analyze_server_action_code
from code_intelligence.knowledge_rules.server_actions.llm import interpret_server_action_with_llm


SUDO_BYPASS_CODE = """
FOURNISSEURS_PRIVILEGIES = [42, 108, 231]
if record.partner_id.id in FOURNISSEURS_PRIVILEGIES:
    record.sudo().action_validate()
"""

CLEAN_CODE = """
record.write({'state': 'done'})
"""


def _mock_llm(content: str) -> Mock:
    m = Mock()
    m.invoke.return_value = SimpleNamespace(content=content)
    return m


# ---------------------------------------------------------------------------
# Bounded invocation: only called when static analysis found something
# ---------------------------------------------------------------------------

def test_interpret_skips_llm_when_no_security_warnings():
    static_analysis = analyze_server_action_code(CLEAN_CODE, "test.action_clean")
    assert not static_analysis.security_warnings

    mock_llm = Mock()
    result = interpret_server_action_with_llm(static_analysis, CLEAN_CODE, mock_llm)

    mock_llm.invoke.assert_not_called()
    assert result.llm_confidence is None
    assert result.llm_summary is None


def test_interpret_calls_llm_when_warnings_present():
    static_analysis = analyze_server_action_code(SUDO_BYPASS_CODE, "test.action_bypass")
    assert static_analysis.security_warnings  # sanity: sudo + hardcoded ids detected

    mock_llm = _mock_llm('{"summary": "Bypasses approval for 3 privileged suppliers via sudo().", "confidence": "medium"}')
    result = interpret_server_action_with_llm(static_analysis, SUDO_BYPASS_CODE, mock_llm)

    mock_llm.invoke.assert_called_once()
    assert result.llm_confidence == "medium"
    assert "sudo" in result.llm_summary.lower() or "bypass" in result.llm_summary.lower()


# ---------------------------------------------------------------------------
# Static confidence must never be touched by the LLM pass
# ---------------------------------------------------------------------------

def test_static_confidence_untouched_by_llm_interpretation():
    static_analysis = analyze_server_action_code(SUDO_BYPASS_CODE, "test.action_bypass")
    mock_llm = _mock_llm('{"summary": "High risk bypass.", "confidence": "high"}')
    result = interpret_server_action_with_llm(static_analysis, SUDO_BYPASS_CODE, mock_llm)

    assert result.confidence == "low", (
        "The static regex-based confidence field must remain fixed at 'low' "
        "regardless of what the LLM reports -- llm_confidence is a SEPARATE "
        "field, never a replacement, per plan J9's rule against presenting "
        "LLM-derived interpretation as a certain structural fact."
    )
    assert result.llm_confidence == "high"


# ---------------------------------------------------------------------------
# Confidence must be bounded to a closed set -- never trust free-form output
# ---------------------------------------------------------------------------

def test_interpret_rejects_out_of_set_confidence():
    static_analysis = analyze_server_action_code(SUDO_BYPASS_CODE, "test.action_bypass")
    mock_llm = _mock_llm('{"summary": "Some summary.", "confidence": "extremely certain"}')
    result = interpret_server_action_with_llm(static_analysis, SUDO_BYPASS_CODE, mock_llm)

    assert result.llm_confidence is None, (
        "A confidence value outside {'high','medium','low'} must be rejected, "
        "not silently accepted -- same closed-list discipline as the business "
        "resolver's bounded LLM arbitration."
    )


def test_interpret_rejects_malformed_json_response():
    static_analysis = analyze_server_action_code(SUDO_BYPASS_CODE, "test.action_bypass")
    mock_llm = _mock_llm("this is not json at all")
    result = interpret_server_action_with_llm(static_analysis, SUDO_BYPASS_CODE, mock_llm)

    assert result.llm_confidence is None
    assert result.llm_summary is None


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

def test_interpret_falls_back_gracefully_on_llm_failure():
    static_analysis = analyze_server_action_code(SUDO_BYPASS_CODE, "test.action_bypass")
    mock_llm = Mock()
    mock_llm.invoke.side_effect = RuntimeError("simulated API failure")

    result = interpret_server_action_with_llm(static_analysis, SUDO_BYPASS_CODE, mock_llm)

    assert result.llm_confidence is None
    assert result.llm_summary is None
    assert result.confidence == "low"  # static analysis result still intact


def test_interpret_falls_back_when_llm_is_none():
    static_analysis = analyze_server_action_code(SUDO_BYPASS_CODE, "test.action_bypass")
    result = interpret_server_action_with_llm(static_analysis, SUDO_BYPASS_CODE, None)

    assert result.llm_confidence is None
    assert result.llm_summary is None
    assert result.security_warnings  # static warnings preserved unchanged


# ---------------------------------------------------------------------------
# Summary text must clearly separate static facts from LLM interpretation
# ---------------------------------------------------------------------------

def test_summary_text_labels_llm_section_distinctly():
    static_analysis = analyze_server_action_code(SUDO_BYPASS_CODE, "test.action_bypass")
    mock_llm = _mock_llm('{"summary": "Bypasses approval for privileged suppliers.", "confidence": "medium"}')
    result = interpret_server_action_with_llm(static_analysis, SUDO_BYPASS_CODE, mock_llm)

    assert "interprétation" in result.summary_text.lower() or "llm" in result.summary_text.lower(), (
        "The LLM-derived section must be visibly labeled as interpretation, "
        "distinct from the static pattern-detection facts above it."
    )



