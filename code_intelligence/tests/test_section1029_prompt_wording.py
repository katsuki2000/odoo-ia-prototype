"""
Section 1029: system prompt wording for unavailable actions and group naming.

PUR-Q4 answered "l'utilisateur doit etre ajoute au groupe Administrator": an
operational recommendation the observations never establish, and a harmful one
(that group carries every purchase approval right, not just the one button).
"""

from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT


def test_unavailable_action_rule_forbids_access_recommendations():
    assert "state which group holds this option and stop there" in CI_SYSTEM_PROMPT
    assert "never recommend adding the demandeur to a group" in CI_SYSTEM_PROMPT
    assert "who they should contact instead" not in CI_SYSTEM_PROMPT


def test_group_naming_rule_forbids_repeating_the_technical_identifier():
    assert "without repeating its technical identifier next to it" in CI_SYSTEM_PROMPT
