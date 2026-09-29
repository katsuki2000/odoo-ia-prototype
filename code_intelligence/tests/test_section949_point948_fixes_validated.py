"""
code_intelligence/tests/test_section949_point948_fixes_validated.py

todo/contexte.txt Section 949: validates the two root-cause fixes already
present in the working tree for section 948's constats 2 and 3 (written
but left untested/unlogged by a prior session).

1. SAL-Q1 self-contradiction (access_guards.py::_flag_ungrounded_group_xmlids):
   a group xml_id sourced only via evaluate_record_rules' own
   "(groupes: ...)" formatting -- as written verbatim by the section 946
   escalation backfill -- must now be recognized as grounded and must not
   be flagged as a possible hallucination.

2. MNT-Q3 / ACC-Q3 technical-citation leak
   (structure.py::_extract_module_extended_models /
   _correct_module_extension_contradiction): the coverage guard's
   denominator must be filtered through the same _is_technical_or_transient
   predicate the curated tool output already uses, so a module extending
   only technical/config models is never told to cite them, and a module
   with many technical entries is not held to an unreachable threshold.
"""

from code_intelligence.agent.access_guards import _flag_ungrounded_group_xmlids
from code_intelligence.rules.structure import (
    _extract_module_extended_models,
    _correct_module_extension_contradiction,
    _strip_irrelevant_inheritance_constraints,
    trace_full_inheritance,
)
import networkx as nx


# ── Point 2: SAL-Q1 grounding via evaluate_record_rules "(groupes: ...)" ──

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

# Answer as it stands after the section 946 backfill: the escalation group
# xmlid is written bare (no "xml_id:" prefix, no has_group() line for it).
SALE_Q1_ANSWER_WITH_BACKFILL = (
    "Le vendeur ne peut voir que les commandes dont il est le vendeur ou "
    "les commandes sans vendeur assigné.\n\n"
    "[FAIT DÉTERMINISTIQUE] Un utilisateur appartenant en plus au groupe "
    "`sales_team.group_sale_salesman_all_leads` ('User: All Documents') ne "
    "serait plus soumis à cette restriction : la règle 'All Orders' "
    "(xml_id: sale.sale_order_see_all) lève alors toute limitation pour ce "
    "modèle."
)


def test_backfilled_escalation_group_is_no_longer_flagged_ungrounded():
    result = _flag_ungrounded_group_xmlids(SALE_Q1_ANSWER_WITH_BACKFILL, SALE_Q1_RAW_OUTPUT)
    assert result == SALE_Q1_ANSWER_WITH_BACKFILL
    assert "NON VÉRIFIÉ" not in result


def test_group_absent_from_groupes_block_still_flagged():
    """No loss of protection: a group xmlid grounded in NEITHER has_group()
    NOR any '(groupes: ...)' block is still flagged."""
    answer = SALE_Q1_ANSWER_WITH_BACKFILL + " Voir aussi `account.group_account_manager`."
    result = _flag_ungrounded_group_xmlids(answer, SALE_Q1_RAW_OUTPUT)
    assert "GROUPE(S) NON VÉRIFIÉ(S)" in result
    assert "account.group_account_manager" in result
    assert "sales_team.group_sale_salesman_all_leads" not in result.split(
        "GROUPE(S) NON VÉRIFIÉ(S) :"
    )[1].split(" mentionné")[0]


# ── Point 3: technical/transient models excluded from coverage denominator ─

def test_extract_module_extended_models_filters_technical_models():
    raw = (
        "Module 'maintenance' defines or extends the following models: "
        "res.config.settings (extends)."
    )
    assert _extract_module_extended_models(raw) == []


def test_extract_module_extended_models_keeps_business_models():
    raw = (
        "Module 'account' defines or extends the following models: "
        "product.product (extends), res.partner (extends), "
        "ir.actions.report (extends), onboarding.onboarding.step (extends)."
    )
    assert _extract_module_extended_models(raw) == ["product.product", "res.partner"]


def test_mnt_q3_technical_only_extension_produces_no_raw_dump():
    """MNT-Q3 shape: the module only extends a technical/config model. The
    question is about model nature / mixin role (inheritance-related), not
    a direct 'quel modele' inquiry -- before the fix, the coverage guard
    still fired on the lone technical model and appended a raw dump."""
    raw = (
        "Module 'maintenance' defines or extends the following models: "
        "res.config.settings (extends)."
    )
    question = (
        "maintenance.equipment est-il un nouveau modele ? Quel est le role "
        "de maintenance.mixin dans son heritage ?"
    )
    answer = (
        "maintenance.equipment est un nouveau modèle. maintenance.mixin est "
        "un mixin technique fournissant le suivi de propriétaire "
        "(owner_user_id) et de date d'assignation (assign_date)."
    )
    fixed = _correct_module_extension_contradiction(answer, raw, question=question)
    assert fixed == answer
    assert "res.config.settings" not in fixed
    assert "À noter : ce module étend bien" not in fixed


def test_inheritance_answer_drops_unrelated_sql_proof():
    answer = "Le modèle est nouveau.\n\nPrécision issue de la preuve SQL : state = 'sale' exige date_order."
    fixed = _strip_irrelevant_inheritance_constraints(
        answer, "sale.order est-il un nouveau modele ou une extension ? Quel modele natif le module sale etend-il ?"
    )
    assert "preuve SQL" not in fixed


def test_mixin_trace_exposes_reusable_fields_and_users():
    graph = nx.DiGraph()
    graph.add_node("model:demo.mixin", node_type="Model", name="demo.mixin")
    graph.add_node("model:demo.asset", node_type="Model", name="demo.asset")
    graph.add_edge("model:demo.asset", "model:demo.mixin", edge_type="EXTENDS")
    graph.add_node(
        "field:demo.mixin.shared_date", node_type="Field", model="demo.mixin", name="shared_date"
    )
    graph.add_node(
        "method:demo.mixin._compute_metric", node_type="Method", model="demo.mixin", name="_compute_metric"
    )
    result = trace_full_inheritance(graph, "demo.mixin")
    assert "réutilisable" in result.summary_text
    assert "shared_date" in result.summary_text


def test_acc_q3_business_models_already_cited_produces_no_raw_dump():
    """ACC-Q3 shape: 25 raw extended models, ~23 technical/transient noise,
    2 real business models -- both already cited by name in the synthesis.
    Coverage on the raw denominator (2/25 = 8%) would wrongly fail the 30%
    threshold; coverage on the filtered denominator (2/2 = 100%) passes."""
    noise = ", ".join(f"ir.model_{i} (extends)" for i in range(23))
    raw = (
        "Module 'account' defines or extends the following models: "
        f"{noise}, product.product (extends), res.partner (extends)."
    )
    question = "Le module account étend-il des modèles natifs hors de son propre périmètre ?"
    answer = (
        "Oui, le module account étend directement les modèles natifs "
        "'product.product' et 'res.partner' hors de son propre périmètre, "
        "en plus de modèles techniques internes non pertinents pour "
        "l'utilisateur métier."
    )
    fixed = _correct_module_extension_contradiction(answer, raw, question=question)
    assert fixed == answer
    assert "ir.model_" not in fixed
    assert "À noter : ce module étend bien" not in fixed


def test_acc_q3_style_still_flags_when_business_models_truly_uncited():
    """Regression guard: filtering the denominator must not silence the
    guard entirely -- a synthesis citing NEITHER real business model must
    still trigger the backfill (with only the filtered/real models, never
    the raw technical noise)."""
    noise = ", ".join(f"ir.model_{i} (extends)" for i in range(23))
    raw = (
        "Module 'account' defines or extends the following models: "
        f"{noise}, product.product (extends), res.partner (extends)."
    )
    question = "Le module account étend-il des modèles natifs hors de son propre périmètre ?"
    answer = "Oui, le module account étend des modèles hors de son propre périmètre."
    fixed = _correct_module_extension_contradiction(answer, raw, question=question)
    assert "À noter : ce module étend bien 2 modèle(s)" in fixed
    assert "product.product" in fixed
    assert "res.partner" in fixed
    assert "ir.model_" not in fixed
