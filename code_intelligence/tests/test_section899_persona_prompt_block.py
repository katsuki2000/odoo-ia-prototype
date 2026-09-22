"""Section 899 -- `build_persona_prompt_block` (durcissement de la consigne
[PERSONAS DE LA QUESTION], suite aux rechutes SAL-Q1/897 et MNT-Q1/898). Un
test unitaire ne peut PAS prouver qu'un LLM obeira a une consigne de prompt --
ces tests verifient seulement que le texte genere contient bien les elements
exiges par le mandat (compte, avertissement PRIOR TOOL OBSERVATIONS, etc.),
et la non-regression du cas vide."""
from code_intelligence.agent.prompts import build_persona_prompt_block


def test_empty_security_principals_yields_empty_string():
    """Non-regression (889, exigence 5) : sans persona, comportement de
    production inchange -- rien n'est ajoute au prompt."""
    assert build_persona_prompt_block({}) == ""
    assert build_persona_prompt_block(None) == ""


def test_single_principal_mnt_q1_style():
    text = build_persona_prompt_block(
        {"utilisateur_simple": {"group_xmlids": ["base.group_user"]}}
    )
    assert "OBLIGATOIRE" in text
    assert "utilisateur_simple" in text
    assert "base.group_user" in text
    assert "1 persona" in text
    assert "1 appel" in text
    assert "PRIOR TOOL OBSERVATIONS" in text
    assert "DEMANDEUR REEL" in text
    assert "principal_id=" in text
    assert "user_groups_json" in text


def test_two_principals_sal_q1_style():
    text = build_persona_prompt_block({
        "salesperson": {"group_xmlids": ["sales_team.group_sale_salesman"]},
        "portal_user": {"group_xmlids": ["base.group_portal"]},
    })
    assert "2 persona" in text
    assert "2 appel" in text
    assert "salesperson" in text
    assert "sales_team.group_sale_salesman" in text
    assert "portal_user" in text
    assert "base.group_portal" in text
    assert "PRIOR TOOL OBSERVATIONS" in text
    assert "DEMANDEUR REEL" in text


def test_warns_prior_observations_answer_no_persona():
    """Adresse directement l'hypothese non verifiee de 892 (le LLM pourrait
    prendre les observations du vrai demandeur, vues plus loin dans le
    prompt, pour une reponse deja suffisante)."""
    text = build_persona_prompt_block(
        {"x": {"group_xmlids": ["mod.group_x"]}}
    )
    assert "NE REPOND A AUCUNE" in text
    assert "ne dispense d'AUCUN" in text
