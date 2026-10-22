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

"""

from code_intelligence.agent.provenance import _flag_ungrounded_group_xmlids
from code_intelligence.rules.structure import trace_full_inheritance
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
