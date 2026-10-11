from code_intelligence.agent.prompts import build_synthesis_prompt
from code_intelligence.rules.navigation import ORPHAN_ACTION_MARKER


def test_prompt_forbids_speculation_when_the_action_has_no_menu():
    observation = f"Aucun menu n'ouvre 'm'. Une action fenetre le cible, mais {ORPHAN_ACTION_MARKER}."
    prompt = build_synthesis_prompt("comment creer ?", [observation], ["describe_navigation_path"])
    assert "do not advise contacting an administrator" in prompt
    assert "never combine the negation 'pas' with 'aucun'" in prompt


def test_prompt_is_unchanged_for_other_observations():
    prompt = build_synthesis_prompt("comment creer ?", ["Menu: Achats > Demandes"], ["describe_navigation_path"])
    assert "attached to no menu" not in prompt
