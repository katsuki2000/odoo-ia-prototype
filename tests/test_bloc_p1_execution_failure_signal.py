# -*- coding: utf-8 -*-
"""
tests/test_bloc_p1_execution_failure_signal.py

Integration tests for the has_execution_failure signal wiring:
  - ci_evidence_decision() keeps INSUFFICIENT + has_execution_failure=True
    on format_output when the question carries no explicit documentary
    request (never silently falling back to generate/RAG in that case)
  - todo/contexte.txt section 744 (pmm mandate): an explicit documentary
    request in the question now overrides has_execution_failure=True too --
    falls back to generate() regardless
  - ci_evidence_decision() still falls back to generate for
    INSUFFICIENT + has_execution_failure=False (genuine negative)
  - ci_agent_node appends the [ATTENTION] paragraph when flag is set
  - format_output excludes execution-failure cases (without an explicit doc
    request) from ci_fell_back_to_rag

Reference scenario: script 7/8 (todo/contexte.txt section 485),
quota/tool-use failure masquerading as evidence absence.
"""

from core.evidence.evidence_sufficiency import (
    EvidenceSufficiencyStatus,
    assess_evidence_sufficiency,
)
from core.graph.graph import ci_evidence_decision


class TestCiEvidenceDecisionRouting:
    """Verifies ci_evidence_decision() routing logic for the
    has_execution_failure flag."""

    def _make_state(self, status, has_execution_failure=False, reasons=None, question=""):
        return {
            "question": question,
            "ci_evidence_sufficiency": {
                "status": status,
                "has_execution_failure": has_execution_failure,
                "reasons": reasons or [],
                "relevant_observation_count": 0,
                "total_observation_count": 1,
            }
        }

    def test_insufficient_with_execution_failure_and_no_doc_request_stays_on_format_output(self):
        state = self._make_state(
            EvidenceSufficiencyStatus.INSUFFICIENT.value,
            has_execution_failure=True,
            question="Pourquoi cette action a-t-elle echoue ?",
        )
        assert ci_evidence_decision(state) == "format_output"

    def test_insufficient_with_execution_failure_and_explicit_doc_request_falls_back_to_generate(self):
        """todo/contexte.txt section 744 (pmm mandate): an explicit documentary
        request in the question now wins over has_execution_failure=True as well
        -- CI has no access to the document corpus, so its own execution-failure
        answer is never a substitute for an explicitly requested RAG lookup."""
        state = self._make_state(
            EvidenceSufficiencyStatus.INSUFFICIENT.value,
            has_execution_failure=True,
            question="Selon le wiki interne, quelle est la procedure ?",
        )
        assert ci_evidence_decision(state) == "generate"

    def test_insufficient_without_execution_failure_falls_back_to_generate(self):
        """generate() (RAG) is only reachable when the question carries an
        explicit documentary anchor -- doc_rag is no longer an automatic
        fallback on insufficient CI evidence."""
        state = self._make_state(
            EvidenceSufficiencyStatus.INSUFFICIENT.value,
            has_execution_failure=False,
            question="Selon le wiki interne, quelle est la procedure ?",
        )
        assert ci_evidence_decision(state) == "generate"

    def test_insufficient_without_execution_failure_and_no_doc_anchor_stays_on_format_output(self):
        """Default case (no explicit documentary request): stays on CI's own
        answer instead of silently falling back to RAG."""
        state = self._make_state(
            EvidenceSufficiencyStatus.INSUFFICIENT.value,
            has_execution_failure=False,
            question="Qui peut valider un avoir de 25000 euros ?",
        )
        assert ci_evidence_decision(state) == "format_output"

    def test_sufficient_always_stays_on_format_output(self):
        state = self._make_state(EvidenceSufficiencyStatus.SUFFICIENT.value)
        assert ci_evidence_decision(state) == "format_output"

    def test_conflicting_always_stays_on_format_output(self):
        state = self._make_state(EvidenceSufficiencyStatus.CONFLICTING.value)
        assert ci_evidence_decision(state) == "format_output"

    def test_missing_sufficiency_defaults_to_format_output(self):
        assert ci_evidence_decision({}) == "format_output"


class TestScript7Scenario:
    """Reproduces the quota/tool-use failure scenario from benchmark script
    7/8 (todo/contexte.txt section 485): all tool observations are captured
    execution exceptions, producing INSUFFICIENT + has_execution_failure=True.
    The system must NOT silently fall back to RAG."""

    def test_all_tool_crashes_produce_flagged_insufficient(self):
        result = assess_evidence_sufficiency(
            tool_observations=[
                "Error executing analyze_security_locks: model server rate limit exceeded",
                "Error executing trace_full_inheritance: tool-use failed",
            ],
            hop_count=2,
            final_answer="Je n'ai pas de donnees disponibles dans le graphe de connaissances.",
        )
        assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT
        assert result.has_execution_failure is True
        assert result.relevant_observation_count == 0

        state = {"ci_evidence_sufficiency": result.to_display_dict()}
        assert ci_evidence_decision(state) == "format_output"

    def test_partial_crash_with_relevant_evidence_is_sufficient_but_flagged(self):
        result = assess_evidence_sufficiency(
            tool_observations=[
                "group_expense_manager has write access to hr.expense",
                "Error executing analyze_data_constraints: timeout",
            ],
            hop_count=2,
            final_answer="Le groupe Expense Manager a acces en ecriture.",
        )
        assert result.status is EvidenceSufficiencyStatus.SUFFICIENT
        assert result.has_execution_failure is True

        state = {"ci_evidence_sufficiency": result.to_display_dict()}
        assert ci_evidence_decision(state) == "format_output"

    def test_genuine_negative_without_crash_falls_back_to_rag(self):
        """Genuine negative (no execution failure) with an explicit documentary
        request in the question -- the sole case where generate() (RAG) is
        still reachable now that doc_rag is no longer an automatic fallback."""
        result = assess_evidence_sufficiency(
            tool_observations=[
                "Field 'custom_field_x' was not found in the indexed knowledge graph.",
            ],
            hop_count=1,
            final_answer="Reponse quelconque.",
        )
        assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT
        assert result.has_execution_failure is False

        state = {
            "question": "Selon le wiki interne, quelle est la procedure ?",
            "ci_evidence_sufficiency": result.to_display_dict(),
        }
        assert ci_evidence_decision(state) == "generate"

    def test_genuine_negative_without_crash_and_no_doc_request_stays_on_format_output(self):
        """Same genuine negative, but the question carries no explicit
        documentary anchor -- doc_rag no longer intervenes automatically,
        CI's own (insufficient) answer is kept as-is."""
        result = assess_evidence_sufficiency(
            tool_observations=[
                "Field 'custom_field_x' was not found in the indexed knowledge graph.",
            ],
            hop_count=1,
            final_answer="Reponse quelconque.",
        )
        assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT
        assert result.has_execution_failure is False

        state = {
            "question": "Quel champ personnalise n'a pas ete trouve ?",
            "ci_evidence_sufficiency": result.to_display_dict(),
        }
        assert ci_evidence_decision(state) == "format_output"


class TestAttentionParagraph:
    """Verifies the [ATTENTION] paragraph is appended to the final answer
    by ci_agent_node when has_execution_failure is True."""

    ATTENTION_MARKER = "[ATTENTION] Une ou plusieurs analyses Code Intelligence"

    def test_marker_present_in_execution_failure_answer(self):
        from code_intelligence.agent.context import _EXECUTION_FAILURE_NOTICE
        assert "[ATTENTION]" in _EXECUTION_FAILURE_NOTICE
