"""
Section 955 (todo/contexte.txt sections 952/954): synthesis-inversion
correction for who_has_access_to verdicts.

STK-Q1's root cause (confirmed in section 954 by rejouer who_has_access_to
directly against the graph, no LLM involved) was NOT a data/tool/truncation
defect -- the observation was already correct on both permissions, the LLM's
own prose asserted the exact opposite. This is deliberately out of scope for
H3/EvidenceSufficiencyStatus.CONFLICTING (see that status's own docstring):
CONFLICTING is reserved for two VALID findings disagreeing with each other,
not a single unambiguous fact the synthesis inverted. It belongs to the same
splice-out-and-replace family as _correct_can_view_amount_contradictions /
_correct_security_lock_threshold_contradictions.
"""

from code_intelligence.rules.access_evaluator import _correct_access_permission_contradictions
from code_intelligence.rules.security_locks import _backfill_missing_approval_guard_facts
from code_intelligence.rules.button_path import (
    correct_button_role_contradictions,
    correct_button_visibility_contradictions,
)
from code_intelligence.agent.postprocess import (
    _strip_unexpected_script_sentences,
    _strip_unsourced_examples,
)


# The exact STK-Q1 verbatim from captures/bloc_n1_verbatim.json (section 952/954).
_STK_Q1_VERBATIM = (
    "### Acc\u00e8s aux quantit\u00e9s en stock\n\n"
    "Un employ\u00e9 \u00ab simple \u00bb (groupe : *Internal User*) **ne peut pas consulter** "
    "les quantit\u00e9s affich\u00e9es dans le module *Inventaire* (mod\u00e8le : `stock.quant`). "
    "Seuls les utilisateurs appartenant au groupe *Gestionnaire de stock* ont la "
    "permission de voir ces informations.\n\n"
    "### Modification d\u2019une ligne de mouvement\n\n"
    "Concernant les lignes de mouvement (`stock.move.line`), un employ\u00e9 \u00ab simple \u00bb "
    "**ne poss\u00e8de pas le droit de modifier** ces enregistrements. Seuls les "
    "utilisateurs du groupe *Gestionnaire de stock* peuvent apporter des changements "
    "\u00e0 ces lignes.\n\n"
    "[Source: Graphe de Connaissances Code Intelligence]"
)

_STK_Q1_OBSERVATION = (
    "Group 'base.group_user' ('Internal User') HAS READ access to 'stock.quant'. "
    "(xml_id: access_stock_quant_all)\n\n"
    "Group 'base.group_user' ('Internal User') HAS WRITE access to 'stock.move.line'. "
    "(xml_id: access_stock_move_line_all)"
)


def test_stk_q1_both_denials_are_corrected_to_match_the_observation():
    corrected = _correct_access_permission_contradictions(_STK_Q1_VERBATIM, _STK_Q1_OBSERVATION)
    assert "L'utilisateur PEUT consulter `stock.quant`" in corrected
    assert "L'utilisateur PEUT modifier `stock.move.line`" in corrected
    assert "ne peut pas consulter" not in corrected
    assert "ne poss\u00e8de pas le droit de modifier" not in corrected


def test_reverse_case_a_wrongly_asserted_allow_is_corrected_to_deny():
    final_answer = (
        "L'employ\u00e9 peut consulter `stock.quant` sans restriction. "
        "[Source: Graphe de Connaissances Code Intelligence]"
    )
    observation = "Group 'base.group_user' ('Internal User') DOES NOT HAVE READ access to 'stock.quant'."
    corrected = _correct_access_permission_contradictions(final_answer, observation)
    assert "NE PEUT PAS consulter `stock.quant`" in corrected
    assert "sans restriction" not in corrected


def test_no_change_when_prose_already_agrees_with_the_observation():
    final_answer = (
        "L'employ\u00e9 peut consulter `stock.quant` librement. "
        "[Source: Graphe de Connaissances Code Intelligence]"
    )
    observation = "Group 'base.group_user' ('Internal User') HAS READ access to 'stock.quant'."
    corrected = _correct_access_permission_contradictions(final_answer, observation)
    assert corrected == final_answer


def test_no_observation_facts_is_a_no_op():
    final_answer = "Une r\u00e9ponse quelconque sans rapport avec who_has_access_to."
    assert _correct_access_permission_contradictions(final_answer, "") == final_answer
    assert _correct_access_permission_contradictions(final_answer, "no fact here") == final_answer


def test_button_visibility_expression_is_not_inverted():
    raw = (
        "Button 'Approve Order' on 'purchase.order': Calls 'button_approve()'. "
        "Required Groups: [purchase.group_purchase_manager]. "
        "Visibility: invisible='state != 'to approve''"
    )
    answer = (
        "2. **Condition de visibilité erronée** : `state != 'to approve'` "
        "empêche l'affichage au statut to approve."
    )
    corrected = correct_button_visibility_contradictions(answer, raw)
    assert "Condition de visibilité inversée" not in corrected
    assert "Condition de visibilité erronée" not in corrected
    assert "state == 'to approve'" in corrected


def test_sentence_about_a_different_model_is_left_untouched():
    final_answer = (
        "L'utilisateur ne peut pas consulter `sale.order`. "
        "[Source: Graphe de Connaissances Code Intelligence]"
    )
    observation = "Group 'base.group_user' ('Internal User') HAS READ access to 'stock.quant'."
    corrected = _correct_access_permission_contradictions(final_answer, observation)
    assert corrected == final_answer


def test_all_four_permission_verbs_are_recognised():
    cases = [
        ("READ", "consulter"),
        ("WRITE", "modifier"),
        ("CREATE", "cr\u00e9er"),
        ("UNLINK", "supprimer"),
    ]
    for permission, verb in cases:
        final_answer = f"L'utilisateur ne peut pas {verb} `res.partner`. [Source: X]"
        observation = f"Group 'base.group_user' ('Internal User') HAS {permission} access to 'res.partner'."
        corrected = _correct_access_permission_contradictions(final_answer, observation)
        assert f"PEUT {verb}" in corrected, f"permission={permission} verb={verb} not corrected: {corrected}"


def test_section956_stk_q1_rejeu_denial_in_prior_sentence_and_bold_markers_are_corrected():
    """Regression pin for the exact rejeu that exposed 2 new gaps in the
    section 955 fix (todo/contexte.txt section 956): the denial sentence
    ("ne peut pas consulter les quantit\u00e9s en stock") never names
    `stock.quant` at all -- only the FOLLOWING sentence does -- and Markdown
    bold markers ("**ne peut pas**") sit between the negation and the verb."""
    final_answer = (
        "### Consultation des quantit\u00e9s en stock\n\n"
        "Un simple employ\u00e9 (groupe \u00ab Internal User \u00bb) **ne peut pas** consulter "
        "les quantit\u00e9s en stock.  \n"
        "Seuls les utilisateurs appartenant au groupe \u00ab Gestionnaire de stock \u00bb ont "
        "l\u2019autorisation de voir les enregistrements de **stock.quant**.\n\n"
        "### Modification d\u2019une ligne de mouvement\n\n"
        "Un simple employ\u00e9 **peut** modifier une ligne de mouvement (**stock.move.line**).  \n"
        "Aucune r\u00e8gle de s\u00e9curit\u00e9 ne restreint l\u2019acc\u00e8s en lecture ou en "
        "\u00e9criture \u00e0 ce mod\u00e8le pour ce groupe.\n\n"
        "[Source: Graphe de Connaissances Code Intelligence]"
    )
    observation = (
        "Group 'base.group_user' ('Internal User') HAS READ access to 'stock.quant'.\n\n"
        "Group 'base.group_user' ('Internal User') HAS WRITE access to 'stock.move.line'."
    )
    corrected = _correct_access_permission_contradictions(final_answer, observation)
    assert "L'utilisateur PEUT consulter `stock.quant`" in corrected
    assert "**ne peut pas** consulter les quantit\u00e9s en stock" not in corrected
    # The WRITE paragraph was already correct and must stay untouched.
    assert "Un simple employ\u00e9 **peut** modifier une ligne de mouvement (**stock.move.line**)." in corrected


def test_section956_embedded_model_period_does_not_truncate_the_sentence():
    """A dotted model name has its OWN internal period ("stock.quant"); a
    naive split on the first '.' truncated the sentence right after "stock."
    and left the rest ("sans restriction. [Source: ...]") glued onto the
    replacement verbatim."""
    final_answer = (
        "L'utilisateur peut consulter `stock.quant` sans aucune restriction particuli\u00e8re. "
        "[Source: Graphe de Connaissances Code Intelligence]"
    )
    observation = "Group 'base.group_user' ('Internal User') DOES NOT HAVE READ access to 'stock.quant'."
    corrected = _correct_access_permission_contradictions(final_answer, observation)
    assert corrected == (
        "L'utilisateur NE PEUT PAS consulter `stock.quant` (voir le fait d\u00e9terministe ci-dessous). "
        "[Source: Graphe de Connaissances Code Intelligence]"
    )


def test_approval_guard_facts_are_backfilled_when_synthesis_drops_them():
    observation = (
        "def _approval_allowed(self):\n"
        "return (self.company_id.po_double_validation == 'one_step' or "
        "(self.company_id.po_double_validation == 'two_step' and "
        "self.amount_total < self.company_id.po_double_validation_amount) or "
        "self.user_has_groups('purchase.group_purchase_manager'))"
    )
    answer = _backfill_missing_approval_guard_facts(
        "Les ACL des deux groupes sont identiques.",
        observation,
        "Qu'est-ce qui distingue un simple acheteur d'un manager sur une commande d'achat ?",
    )

    assert "_approval_allowed()" in answer
    assert "one_step" in answer
    assert "two_step" in answer
    assert "purchase.group_purchase_manager" in answer


def test_button_role_contradiction_is_clarified_from_execution_path():
    answer = "Le manager peut utiliser confirm_reminder_mail() pour finaliser la commande."
    observation = (
        "Button 'Confirm Receipt Date' on 'purchase.order': Calls "
        "'confirm_reminder_mail()'. Required Groups: [base.group_no_one]."
    )

    corrected = correct_button_role_contradictions(answer, observation)

    assert "ne permet pas d'attribuer" in corrected
    assert "base.group_no_one" in corrected
    assert "Le manager peut utiliser confirm_reminder_mail()" not in corrected


def test_orphaned_markdown_heading_is_removed_after_button_role_correction():
    answer = (
        "### Différences\n\n"
        "3. **Gestion des états avancés**\n"
        "- Le manager peut utiliser confirm_reminder_mail() pour finaliser la commande.\n\n"
        "### En résumé\n\n"
        "Le manager garde des privilèges supplémentaires."
    )
    observation = (
        "Button 'Confirm Receipt Date' on 'purchase.order': Calls "
        "'confirm_reminder_mail()'. Required Groups: [base.group_no_one]."
    )

    corrected = correct_button_role_contradictions(answer, observation)

    assert "Gestion des états avancés" not in corrected
    assert "### En résumé" in corrected


def test_unexpected_han_sentence_is_removed_without_affecting_french_prose():
    answer = (
        "La suppression est bloquée pour les états purchase et done. "
        "Ces états indiquent que la ligne est active ou已完成, et doit être annulée.\n\n"
        "La contrainte SQL reste applicable."
    )

    cleaned = _strip_unexpected_script_sentences(answer)

    assert "purchase et done" in cleaned
    assert "已完成" not in cleaned
    assert "La contrainte SQL reste applicable." in cleaned


def test_unsourced_example_block_is_removed_from_the_final_answer():
    answer = (
        "La règle limite la consultation aux abonnés.\n\n"
        "**Exemple :** Si un équipement est assigné à un contact, il est visible."
    )

    cleaned = _strip_unsourced_examples(answer, "Règle: message_partner_ids contient partner_id.")

    assert cleaned == "La règle limite la consultation aux abonnés."


def test_pur_q4_visibility_error_claim_is_removed():
    raw = (
        "Button 'Approve Order' on 'purchase.order': Calls 'button_approve()'. "
        "Required Groups: [purchase.group_purchase_manager]. "
        "Visibility: invisible='state != 'to approve''. (visible quand state == 'to approve')"
    )
    answer = (
        "### Raisons de l'absence du bouton 'Approve Order'\n\n"
        "Le bouton n'est pas visible pour deux raisons principales :\n\n"
        "1. **Restriction de groupe** : Le bouton est uniquement disponible pour les membres du groupe Administrator.\n\n"
        "2. **Condition de visibilité** : Bien que le statut 'to approve' devrait théoriquement rendre le bouton visible, "
        "une erreur dans la logique de visibilité (`invisible='state != 'to approve''`) pourrait également contribuer à ce comportement."
    )
    corrected = correct_button_visibility_contradictions(answer, raw)
    assert "erreur dans la logique de visibilité" not in corrected
    assert "pour la raison principale suivante :" in corrected
    assert "Restriction de groupe" in corrected
    assert "state == 'to approve'" in corrected
