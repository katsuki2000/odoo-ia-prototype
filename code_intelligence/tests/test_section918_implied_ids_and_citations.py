"""
code_intelligence/tests/test_section918_implied_ids_and_citations.py

Tests for Section 918:
1. get_chat_llm: verifies frequency_penalty and presence_penalty are passed cleanly
   to ChatOpenAI without triggering LangChain UserWarning.
2. CI_SYSTEM_PROMPT: verifies prompt instructions and examples use xml_id: rather than
   the misleading file:///path#L12 placeholder for ACL sources.
"""

import warnings

from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT, build_synthesis_prompt
from core.llm.llm_client import get_chat_llm


class TestGetChatLlmPenaltiesWarning:
    def test_no_warning_when_passing_penalties_in_model_kwargs(self):
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            llm = get_chat_llm(model_kwargs={"frequency_penalty": 0.3, "presence_penalty": 0.2})
            user_warnings = [
                str(w.message) for w in recorded
                if issubclass(w.category, UserWarning) and "penalty" in str(w.message).lower()
            ]
            assert not user_warnings, f"Unexpected penalty UserWarning: {user_warnings}"


class TestPromptCitationGuidelines:
    def test_system_prompt_does_not_contain_literal_path_placeholder_link(self):
        assert "file:///path#L12" not in CI_SYSTEM_PROMPT
        assert "Do NOT append any 'Preuves', 'Sources', or 'Citations' section" in CI_SYSTEM_PROMPT

class TestPromptGrounding:
    def test_group_labels_are_quoted_from_observations_not_invented(self):
        assert "exact display name given in the observations" in CI_SYSTEM_PROMPT
        assert "functional group names in French" not in CI_SYSTEM_PROMPT
        synthesis = build_synthesis_prompt("Test question", ["Obs 1"], ["tool_a"])
        assert "libellé exact tel que donné dans les observations" in synthesis
        assert "noms fonctionnels des groupes" not in synthesis

    def test_output_example_carries_no_concrete_group_label(self):
        # PUR-Q2/PUR-Q4 copied a concrete example label ("Purchase Approvers") for a group
        # whose real display name is "Administrator" (todo/contexte.txt section 939).
        assert "Purchase Approvers" not in CI_SYSTEM_PROMPT
        assert "Responsable des achats" not in CI_SYSTEM_PROMPT
        assert "Responsable des achats" not in build_synthesis_prompt("Test question", ["Obs 1"], ["tool_a"])

    def test_effect_grounding_rule_in_both_prompts(self):
        from code_intelligence.agent.prompts import EFFECT_GROUNDING_RULE
        assert EFFECT_GROUNDING_RULE in CI_SYSTEM_PROMPT
        assert EFFECT_GROUNDING_RULE in build_synthesis_prompt("Test question", ["Obs 1"], ["tool_a"])

    def test_synthesis_prompt_keeps_python_lock_clause(self):
        prompt = build_synthesis_prompt("Test question", ["Obs 1"], ["tool_a"])
        assert "and any Python-level locks" in prompt
