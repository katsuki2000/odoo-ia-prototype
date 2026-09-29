"""
code_intelligence/tests/test_section946_group_escalation_backfill.py

Unit tests for Section 946: backfilling the "escalation group" contrast
when evaluate_record_rules lists an ignored (non-member) group rule using
Odoo's standard unrestricted-access idiom (domain_force (1,'=',1) or
('id','!=',False)) and the question explicitly names that group.
"""

from code_intelligence.agent.access_guards import _backfill_missing_group_escalation_note

SALE_Q1_RAW_OUTPUT = (
    "Évaluation des règles d'enregistrement (ir.rule) pour 'sale.order':\n"
    "  - Règles Globales (ET pour tous): Sales Order multi-company "
    "[[('company_id', 'in', company_ids)]] (xml_id: sale.sale_order_comp_rule)\n"
    "  - Règles de Groupe applicables (combinées en OU): Personal Orders "
    "(groupes: sales_team.group_sale_salesman ('User: Own Documents Only')) "
    "[['|',('user_id','=',user.id),('user_id','=',False)]] "
    "(xml_id: sale.sale_order_personal_rule)\n"
    "  - Règles de Groupe ignorées (non-membre): Portal Personal "
    "Quotations/Sales Orders (groupes: base.group_portal ('Portal')) "
    "[[('message_partner_ids','child_of',[user.commercial_partner_id.id])]] "
    "(xml_id: sale.sale_order_rule_portal), All Orders (groupes: "
    "sales_team.group_sale_salesman_all_leads ('User: All Documents')) "
    "[[(1,'=',1)]] (xml_id: sale.sale_order_see_all)\n"
    "  -> CONCLUSION: Au moins une regle de groupe applicable restreint "
    "potentiellement l'acces."
)

SALE_Q1_QUESTION = (
    "Un vendeur (sales_team.group_sale_salesman, sans "
    "group_sale_salesman_all_leads) peut-il voir toutes les commandes de "
    "vente de son entreprise, ou seulement certaines ?"
)

SALE_Q1_ANSWER = (
    "Le vendeur ne peut voir que les commandes dont il est le vendeur ou "
    "les commandes sans vendeur assigné."
)


def test_backfills_escalation_note_when_question_names_the_group():
    result = _backfill_missing_group_escalation_note(
        SALE_Q1_ANSWER, SALE_Q1_RAW_OUTPUT, SALE_Q1_QUESTION
    )
    assert result != SALE_Q1_ANSWER
    assert "sales_team.group_sale_salesman_all_leads" in result
    assert "sale.sale_order_see_all" in result
    assert "[FAIT DÉTERMINISTIQUE]" in result


def test_no_backfill_when_question_does_not_mention_escalation_group():
    question = "Un vendeur peut-il voir toutes les commandes de vente ?"
    result = _backfill_missing_group_escalation_note(
        SALE_Q1_ANSWER, SALE_Q1_RAW_OUTPUT, question
    )
    assert result == SALE_Q1_ANSWER


def test_always_backfills_even_when_rule_already_mentioned():
    # Section 962: same root-cause fix as implied_ids -- always append the
    # deterministic fact even if the answer's own wording already brushes
    # against the same rule, rather than gating on a substring match against
    # non-deterministic LLM phrasing.
    answer_with_rule = SALE_Q1_ANSWER + " (voir sale_order_see_all)"
    result = _backfill_missing_group_escalation_note(
        answer_with_rule, SALE_Q1_RAW_OUTPUT, SALE_Q1_QUESTION
    )
    assert result != answer_with_rule
    assert "[FAIT DÉTERMINISTIQUE]" in result


def test_no_backfill_for_non_see_all_ignored_rule():
    # Portal rule is ignored too, but its domain is NOT the "sees everything"
    # idiom -- naming it in the question must not trigger a false backfill.
    question = "Un vendeur peut-il voir les commandes vues par base.group_portal ?"
    result = _backfill_missing_group_escalation_note(
        SALE_Q1_ANSWER, SALE_Q1_RAW_OUTPUT, question
    )
    assert result == SALE_Q1_ANSWER


def test_no_backfill_when_no_ignored_group_section():
    raw = "Évaluation des règles d'enregistrement (ir.rule) pour 'sale.order':\n  - Règles Globales: Aucune"
    result = _backfill_missing_group_escalation_note(
        SALE_Q1_ANSWER, raw, SALE_Q1_QUESTION
    )
    assert result == SALE_Q1_ANSWER


def test_no_backfill_for_accounting_field_visibility_question():
    question = (
        "Un Billing Administrator voit-il le compte comptable (account_id) "
        "d'une ligne de facture ?"
    )
    result = _backfill_missing_group_escalation_note(
        SALE_Q1_ANSWER, SALE_Q1_RAW_OUTPUT, question
    )
    assert result == SALE_Q1_ANSWER
