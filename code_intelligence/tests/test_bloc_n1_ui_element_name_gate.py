"""
Bloc N1 (todo/contexte.txt sections 767/768): extract_ui_element_name()
gate coverage for questions that reference the UI element without an
explicit "bouton"/"button"/"champ"/"field" keyword -- the native N1
question bank glosses the French action verb or business term with the
real technical/UI label in parentheses instead.
"""

from code_intelligence.agent.context_extractors import extract_ui_element_name


def test_action_verb_plus_parenthetical_label_sal_q4():
    """'deverrouiller (Unlock)' -- no accent, no 'bouton' keyword."""
    q = (
        "Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) "
        "une commande verrouillee, meme si c'est lui qui l'a confirmee ?"
    )
    assert extract_ui_element_name(q) == "Unlock"


def test_action_verb_plus_parenthetical_label_accented():
    """Same pattern, accented spelling of the verb must also match."""
    q = "Pourquoi ne peut-on pas déverrouiller (Unlock) cette commande ?"
    assert extract_ui_element_name(q) == "Unlock"


def test_bare_technical_field_name_in_parens_acc_q4():
    """'le compte comptable (account_id)' -- no 'champ'/'field' keyword."""
    q = (
        "Un utilisateur avec uniquement group_account_invoice ('Billing') "
        "voit-il le compte comptable (account_id) d'une ligne de facture ?"
    )
    assert extract_ui_element_name(q) == "account_id"


def test_field_name_with_equals_sign_not_matched_as_bare_paren():
    """'(recurring_maintenance=True)' is a field=value aside, not a UI
    element the question is asking about (MNT-Q2, a workflow question) --
    must stay None so the new bare-parenthesis pattern doesn't over-fire."""
    q = (
        "Que se passe-t-il automatiquement quand une demande de maintenance "
        "preventive et recurrente (recurring_maintenance=True) atteint une "
        "etape marquee 'done' ?"
    )
    assert extract_ui_element_name(q) is None


def test_existing_quoted_champ_pattern_unaffected():
    """Non-regression: the pre-existing 'champ '...'' pattern (MNT-Q4) must
    still take priority and keep working exactly as before."""
    q = (
        "Pourquoi le champ 'cost' (cout) d'un equipement n'est-il pas "
        "visible pour tous les utilisateurs ayant acces en lecture a sa "
        "fiche ?"
    )
    assert extract_ui_element_name(q) == "cost"


def test_unrelated_parenthetical_aside_not_matched():
    """A parenthetical aside with no underscore and no trigger verb before
    it must not be mistaken for a UI element name (keeps the new bare-paren
    pattern's false-positive rate low -- it requires an underscore)."""
    q = "Cette regle s'applique-t-elle aussi en debut de mois (janvier) ?"
    assert extract_ui_element_name(q) is None
