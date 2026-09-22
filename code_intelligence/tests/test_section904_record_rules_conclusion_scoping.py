"""Section 904 -- scoping the "no applicable group rule" CONCLUSION line in
evaluate_record_rules() to the exact group set evaluated, instead of an
unqualified "cet utilisateur" claim. Root cause of the MNT-Q1 trap
(893/898/901/902/903): when the persona mechanism (899) is not engaged, this
is the only observation the LLM sees, and its old wording let a blanket
"no restriction for this user" claim (evaluated for the real benchmark
requester) get generalized to an unrelated persona named in the question."""
import networkx as nx

from code_intelligence.rules.record_rules import evaluate_record_rules


def _build_single_group_rule_graph() -> nx.DiGraph:
    """Mirrors the MNT-Q1 shape: one group-scoped rule on a model, restricted
    to a group the evaluated principal does not belong to."""
    G = nx.DiGraph()
    G.add_node("model:maintenance.equipment", node_type="Model", name="maintenance.equipment")
    G.add_node(
        "group:maintenance.group_equipment_manager",
        node_type="Group",
        name="Equipment Manager",
        xml_id="maintenance.group_equipment_manager",
    )
    G.add_node(
        "rule:maintenance.equipment_rule_user",
        node_type="Rule",
        name="equipment_rule_user",
        xml_id="maintenance.equipment_rule_user",
        domain_force="[('message_partner_ids', 'in', [user.partner_id.id])]",
        perm_read=True,
    )
    G.add_edge("model:maintenance.equipment", "rule:maintenance.equipment_rule_user", edge_type="RESTRICTED_BY")
    G.add_edge(
        "rule:maintenance.equipment_rule_user",
        "group:maintenance.group_equipment_manager",
        edge_type="APPLIES_TO_GROUP",
    )
    return G


def test_no_group_rule_applies_conclusion_names_the_evaluated_groups():
    G = _build_single_group_rule_graph()
    res = evaluate_record_rules(G, "maintenance.equipment", user_groups=["base.group_user"])

    assert len(res.applied_group_rules) == 0
    assert len(res.ignored_group_rules) == 1
    assert "base.group_user" in res.summary_text


def test_no_group_rule_applies_conclusion_does_not_generalize_beyond_evaluated_groups():
    """The old wording ("il n'y a AUCUNE restriction [...] pour cet
    utilisateur") is what let the LLM extend a real-requester-only finding
    to an unrelated persona. The new CONCLUSION must explicitly say this
    finding is scoped to the evaluated group set and does not extend to
    any other persona."""
    G = _build_single_group_rule_graph()
    res = evaluate_record_rules(G, "maintenance.equipment", user_groups=["base.group_user"])

    conclusion = res.summary_text
    assert "pour cet utilisateur" not in conclusion
    assert "NE S'ETEND" in conclusion or "ne s'etend" in conclusion.lower()
    assert "AUTRE PERSONA" in conclusion or "autre persona" in conclusion.lower()


def test_no_group_rule_applies_conclusion_handles_empty_group_set():
    """Real benchmark requester case: zero groups. Must still name the
    (empty) evaluated set explicitly rather than silently defaulting to a
    generic phrase that reads as universal."""
    G = _build_single_group_rule_graph()
    res = evaluate_record_rules(G, "maintenance.equipment", user_groups=[])

    conclusion = res.summary_text
    assert "aucun groupe" in conclusion.lower()
    assert "pour cet utilisateur" not in conclusion


def test_group_rule_applies_conclusion_unchanged():
    """Non-regression: the branch where a group rule DOES apply is untouched
    by this fix (root cause of MNT-Q1 is the empty-applied_group branch
    only -- see 904, SAL-Q1's CONCLUSION was already correct in this
    branch and is a separate, unrelated defect)."""
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node(
        "group:sales_team.group_sale_salesman",
        node_type="Group",
        name="Salesman",
        xml_id="sales_team.group_sale_salesman",
    )
    G.add_node(
        "rule:sale.sale_order_personal_rule",
        node_type="Rule",
        name="Personal Orders",
        xml_id="sale.sale_order_personal_rule",
        domain_force="[('user_id', '=', user.id)]",
        perm_read=True,
    )
    G.add_edge("model:sale.order", "rule:sale.sale_order_personal_rule", edge_type="RESTRICTED_BY")
    G.add_edge(
        "rule:sale.sale_order_personal_rule",
        "group:sales_team.group_sale_salesman",
        edge_type="APPLIES_TO_GROUP",
    )

    res = evaluate_record_rules(G, "sale.order", user_groups=["sales_team.group_sale_salesman"])
    assert "Au moins une regle de groupe applicable restreint potentiellement" in res.summary_text
