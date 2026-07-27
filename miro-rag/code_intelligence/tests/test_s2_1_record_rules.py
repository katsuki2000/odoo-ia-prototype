"""
code_intelligence/tests/test_s2_1_record_rules.py

Unit tests for Story S2.1 & S2.2: Odoo Record Rule (ir.rule) Combination Evaluator.
Tests Odoo's exact security algorithm:
  - Global rules (no group) are combined with AND across all users.
  - Group rules are combined with OR for groups the user belongs to.
  - If a user belongs to NO group associated with a group rule, that group rule DOES NOT APPLY to the user.
  - Validates adversarial test 6 (Q6.1 & Q6.2).
"""

import pytest
import networkx as nx

from code_intelligence.deterministic_tools import (
    evaluer_regles_enregistrement,
    qui_a_acces_a,
)


def _build_test_6_knowledge_graph() -> nx.DiGraph:
    """
    Constructs knowledge graph matching Adversarial Module 8 (custom_credit_note_visibility_rules):
     - Model: account.move
     - Rule 1 (Global): Global multi-company rule (no groups)
     - Rule 2 (Regional Group): account.move <= 50,000 EUR (group_regional)
     - Rule 3 (National Group): account.move unlimited (group_national)
    """
    G = nx.DiGraph()

    # Nodes
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node("group:custom_credit_note_visibility_rules.group_regional", node_type="Group", name="Avoirs - Visibilité Régionale", xml_id="custom_credit_note_visibility_rules.group_regional")
    G.add_node("group:custom_credit_note_visibility_rules.group_national", node_type="Group", name="Avoirs - Visibilité Nationale", xml_id="custom_credit_note_visibility_rules.group_national")

    # Global Rule
    G.add_node(
        "rule:custom_credit_note_visibility_rules.rule_global_multi_company",
        node_type="Rule",
        name="Avoirs Global Multi-Company",
        xml_id="custom_credit_note_visibility_rules.rule_global_multi_company",
        domain_force="[('company_id', 'in', company_ids)]",
        perm_read=True,
    )
    G.add_edge("model:account.move", "rule:custom_credit_note_visibility_rules.rule_global_multi_company", edge_type="RESTRICTED_BY")

    # Regional Rule (limit 50,000)
    G.add_node(
        "rule:custom_credit_note_visibility_rules.rule_regional_limit",
        node_type="Rule",
        name="Avoirs Régionaux Plafond 50k",
        xml_id="custom_credit_note_visibility_rules.rule_regional_limit",
        domain_force="[('amount_total', '<=', 50000)]",
        perm_read=True,
    )
    G.add_edge("model:account.move", "rule:custom_credit_note_visibility_rules.rule_regional_limit", edge_type="RESTRICTED_BY")
    G.add_edge("rule:custom_credit_note_visibility_rules.rule_regional_limit", "group:custom_credit_note_visibility_rules.group_regional", edge_type="APPLIES_TO_GROUP")

    # National Rule (unlimited)
    G.add_node(
        "rule:custom_credit_note_visibility_rules.rule_national_unlimited",
        node_type="Rule",
        name="Avoirs Nationaux Illimités",
        xml_id="custom_credit_note_visibility_rules.rule_national_unlimited",
        domain_force="[(1, '=', 1)]",
        perm_read=True,
    )
    G.add_edge("model:account.move", "rule:custom_credit_note_visibility_rules.rule_national_unlimited", edge_type="RESTRICTED_BY")
    G.add_edge("rule:custom_credit_note_visibility_rules.rule_national_unlimited", "group:custom_credit_note_visibility_rules.group_national", edge_type="APPLIES_TO_GROUP")

    return G


def test_q6_1_both_groups_user_can_view_80k():
    """
    Q6.1: User is member of BOTH regional AND national groups.
    Algorithm: (Global) AND (Regional 50k OR National Unlimited) -> National Unlimited wins!
    Result: User CAN view 80,000 EUR credit note.
    """
    G = _build_test_6_knowledge_graph()
    user_groups = [
        "custom_credit_note_visibility_rules.group_regional",
        "custom_credit_note_visibility_rules.group_national",
    ]

    res = evaluer_regles_enregistrement(G, "account.move", user_groups=user_groups)
    assert res.can_view_amount(80000) is True
    assert len(res.applied_global_rules) == 1
    assert len(res.applied_group_rules) == 2
    assert "OR" in res.effective_domain_summary or "Illimités" in res.effective_domain_summary


def test_q6_2_no_groups_user_can_view_80k():
    """
    Q6.2: User belongs to NO groups (neither regional nor national).
    Algorithm: Neither group rule applies! User is restricted ONLY by Global Multi-Company rule.
    Result: User CAN view 80,000 EUR credit note (not restricted by amount).
    """
    G = _build_test_6_knowledge_graph()
    user_groups = []

    res = evaluer_regles_enregistrement(G, "account.move", user_groups=user_groups)
    assert res.can_view_amount(80000) is True
    assert len(res.applied_global_rules) == 1
    assert len(res.applied_group_rules) == 0
    assert len(res.ignored_group_rules) == 2


def test_regional_group_only_user_cannot_view_80k():
    """
    Control test: User is member of ONLY the regional group.
    Algorithm: (Global) AND (Regional 50k).
    Result: User CANNOT view 80,000 EUR credit note (exceeds 50,000 EUR limit).
    """
    G = _build_test_6_knowledge_graph()
    user_groups = ["custom_credit_note_visibility_rules.group_regional"]

    res = evaluer_regles_enregistrement(G, "account.move", user_groups=user_groups)
    assert res.can_view_amount(80000) is False
    assert len(res.applied_group_rules) == 1
    assert res.applied_group_rules[0].rule_xml_id.endswith("rule_regional_limit")
