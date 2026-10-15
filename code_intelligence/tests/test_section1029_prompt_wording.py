"""
Section 1029: system prompt wording for unavailable actions and group naming.

PUR-Q4 answered "l'utilisateur doit etre ajoute au groupe Administrator": an
operational recommendation the observations never establish, and a harmful one
(that group carries every purchase approval right, not just the one button).
"""

from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT, build_synthesis_prompt


def test_unavailable_action_rule_forbids_access_recommendations():
    assert "state which group holds this option and stop there" in CI_SYSTEM_PROMPT
    assert "never recommend adding the demandeur to a group" in CI_SYSTEM_PROMPT
    assert "who they should contact instead" not in CI_SYSTEM_PROMPT


def test_group_naming_rule_forbids_repeating_the_technical_identifier():
    assert "without repeating its technical identifier next to it" in CI_SYSTEM_PROMPT


def test_process_questions_are_routed_to_workflow_and_override_tools():
    assert "how a process is validated or approved in the company" in CI_SYSTEM_PROMPT
    assert "`describe_workflow`, `analyze_method_override_chain` and `analyze_security_locks`" in CI_SYSTEM_PROMPT


def test_a_button_not_found_by_name_is_not_evidence_of_absence():
    assert "never evidence that the process does not exist" in CI_SYSTEM_PROMPT


def test_prompt_examples_do_not_seed_a_validation_button_name():
    assert "action_valider" not in CI_SYSTEM_PROMPT
    assert "bouton Valider" not in CI_SYSTEM_PROMPT


def test_synthesis_prompt_keeps_interface_labels_out_of_the_question_language():
    prompt = build_synthesis_prompt("Test question", ["Obs 1"], ["tool_a"])

    assert "Write the prose in the SAME language as the Original Question" in prompt
    assert "Interface labels (menu, button, field, state and group names" in prompt
    assert "never translate it and never add a translation or gloss next to it" in prompt
    assert "a label absent from the observations is never quoted" in prompt
    assert "never mix languages" not in prompt
