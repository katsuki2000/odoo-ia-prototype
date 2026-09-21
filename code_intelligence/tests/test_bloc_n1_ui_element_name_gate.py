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


# ── Section 876: bare-parenthesis fallback gated by intent, groups excluded ──

from types import SimpleNamespace
from unittest.mock import MagicMock

from code_intelligence.agent.context_extractors import is_group_identifier


def test_group_name_in_parens_is_not_a_ui_element_acc_q2():
    """'(group_account_manager)' names a security group, never a button."""
    q = (
        "Un 'Billing Administrator' (group_account_manager) peut-il poster une "
        "ecriture comptable dont la date est anterieure ou egale a la date de "
        "cloture (lock date) de la societe ?"
    )
    assert extract_ui_element_name(q) is None


def test_group_name_in_parens_is_not_a_ui_element_acc_q1():
    q = (
        "L'ACL directe de account.group_account_manager sur account.move "
        "n'accorde que perm_read=1. Un 'Billing Administrator' "
        "(group_account_manager) peut-il malgre tout creer et modifier des factures ?"
    )
    assert extract_ui_element_name(q) is None


def test_field_in_constraint_question_is_not_a_ui_element_sal_q5():
    """A field named in a CONSTRAINT question is not a UI element ('avoir'
    must not be mistaken for the verb 'voir')."""
    q = (
        "Quelle contrainte empeche une commande confirmee de ne pas avoir de "
        "date de confirmation, et quelle contrainte distincte s'applique sur le "
        "pourcentage d'acompte demande (prepayment_percent) ?"
    )
    assert extract_ui_element_name(q) is None


def test_field_in_constraint_question_is_not_a_ui_element_mnt_q5():
    q = (
        "Quelle regle empeche de creer deux equipements avec le meme numero de "
        "serie, et quelle contrainte distincte s'applique sur l'intervalle de "
        "repetition (repeat_interval) d'une demande recurrente ?"
    )
    assert extract_ui_element_name(q) is None


def test_method_name_in_parens_still_extracted():
    """button_*/action_* in parens are real buttons/methods: PUR-Q2, SAL-Q2,
    STK-Q2 ('que se passe-t-il quand on clique/confirme/valide')."""
    assert extract_ui_element_name(
        "Que se passe-t-il exactement quand on clique sur 'Confirm Order' "
        "(button_confirm) selon que la commande est eligible ou non ?"
    ) == "button_confirm"
    assert extract_ui_element_name(
        "Que se passe-t-il exactement quand on confirme une commande de vente "
        "(action_confirm), et dans quel cas est-elle verrouillee ?"
    ) == "action_confirm"
    assert extract_ui_element_name(
        "Que se passe-t-il quand on valide un transfert de stock "
        "(button_validate) dont les quantites sont inferieures ?"
    ) == "button_validate"


def test_group_skipped_but_later_field_in_visibility_question_kept():
    """The fallback examines every candidate, not just the first: a group
    first, then a field asked about in a visibility question."""
    q = (
        "Un utilisateur du groupe (group_account_manager) voit-il le compte "
        "comptable (account_id) d'une ligne de facture ?"
    )
    assert extract_ui_element_name(q) == "account_id"


def test_is_group_identifier():
    assert is_group_identifier("group_account_manager")
    assert is_group_identifier("account.group_account_manager")
    assert is_group_identifier("base.group_user")
    assert not is_group_identifier("button_confirm")
    assert not is_group_identifier("account_id")
    assert not is_group_identifier("")


def test_dispatch_button_execution_path_skips_group_name():
    """Defense in depth: even if an extraction path yields a group name
    (here the explicit 'bouton <name>' keyword pattern), the dispatcher must
    not call button_execution_path."""
    # Enter through the production entry point (agent.loop): importing
    # predispatch_structure directly hits a pre-existing circular import
    # (agent.context <-> rules.security_evidence), reproduced on HEAD too
    # (todo/contexte.txt section 876) -- not introduced by this test.
    import code_intelligence.agent.loop  # noqa: F401
    from code_intelligence.agent.predispatch_structure import dispatch_button_execution_path

    from unittest.mock import patch

    def _ctx(question):
        return SimpleNamespace(
            concept=SimpleNamespace(is_resolved=True, resolved_models=["account.move"]),
            hop_budget_exhausted=False,
            matched_dispatchers=[],
            question=question,
            tool_map={"button_execution_path": MagicMock()},
            seen_calls=set(),
            G=None,
            resolved_user_group_xmlids=[],
        )

    mod = "code_intelligence.agent.predispatch_structure"
    impl_target = f"{mod}._button_execution_path_impl"
    # _resolve_model_param needs the live knowledge graph; not under test here.
    resolve_target = f"{mod}._resolve_model_param"
    q_group = "Que fait le bouton group_account_manager sur la facture ?"

    # Control: a non-group name reaches the implementation (proves the mock
    # is on the real call path, so the group assertion below is not vacuous).
    with patch(resolve_target, return_value="account.move"), patch(impl_target) as impl:
        dispatch_button_execution_path(_ctx("Que fait le bouton confirm_thing sur la facture ?"))
        assert impl.called

    # A group name never reaches it.
    with patch(resolve_target, return_value="account.move"), patch(impl_target) as impl:
        dispatch_button_execution_path(_ctx(q_group))
        impl.assert_not_called()

    # Negative control: with the group guard defeated, the same group question
    # DOES reach the implementation -- so it is the guard that stops it.
    with patch(resolve_target, return_value="account.move"), patch(impl_target) as impl, \
            patch(f"{mod}.is_group_identifier", return_value=False):
        dispatch_button_execution_path(_ctx(q_group))
        assert impl.called
