"""
code_intelligence/tests/test_s2_1_record_rules.py

Unit tests for  & S2.2: Odoo Record Rule (ir.rule) Combination Evaluator.
Tests Odoo's exact security algorithm:
  - Global rules (no group) are combined with AND across all users.
  - Group rules are combined with OR for groups the user belongs to.
  - If a user belongs to NO group associated with a group rule, that group rule DOES NOT APPLY to the user.
  - Validates adversarial test 6 (Q6.1 & Q6.2).
"""

import pytest
import networkx as nx

from code_intelligence.knowledge_rules.deterministic.access.record_rules import evaluate_record_rules
from code_intelligence.knowledge_rules.deterministic.access.access_evaluator import who_has_access_to


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

    res = evaluate_record_rules(G, "account.move", user_groups=user_groups)
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

    res = evaluate_record_rules(G, "account.move", user_groups=user_groups)
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

    res = evaluate_record_rules(G, "account.move", user_groups=user_groups)
    assert res.can_view_amount(80000) is False
    assert len(res.applied_group_rules) == 1
    assert res.applied_group_rules[0].rule_xml_id.endswith("rule_regional_limit")


def test_group_membership_tolerates_missing_module_prefix():
    """
    Regression guard for a real bug found during J4 benchmark analysis:
    calling evaluate_record_rules with unqualified group names
    (e.g. "group_avoir_national" instead of
    "custom_credit_note_visibility_rules.group_avoir_national") silently
    caused applicable group rules to be misclassified as "ignored
    (non-member)", inverting the access decision for Q6.1/Q6.2 even though
    the underlying AND/OR combination logic was correct. The LLM populating
    user_groups_json in its tool call cannot be relied on to always supply
    the fully-qualified xml_id.
    """
    G = _build_test_6_knowledge_graph()

    # Unqualified group names, as an LLM tool call might supply them
    user_groups = ["group_regional", "group_national"]

    res = evaluate_record_rules(G, "account.move", user_groups=user_groups)
    assert res.can_view_amount(80000) is True, (
        "Short group names without module prefix must still match the "
        "fully-qualified group xml_ids stored on the rules."
    )
    assert len(res.applied_group_rules) == 2
    assert len(res.ignored_group_rules) == 0


def test_group_membership_fuzzy_matches_display_name():
    """
    Regression guard for the REAL bug reproduced end-to-end during J4:
    the LLM's actual tool call for Q6.1 supplied
    user_groups_json = '["regional", "national"]' -- bare words paraphrased
    from the question, not any technical identifier (neither xml_id nor
    short name). This must still resolve via fuzzy match against each
    group's human-readable display name (e.g. "Avoirs - Visibilite
    Nationale").
    """
    G = _build_test_6_knowledge_graph()
    user_groups = ["regional", "national"]  # exact strings the LLM actually sent

    res = evaluate_record_rules(G, "account.move", user_groups=user_groups)
    assert res.can_view_amount(80000) is True, (
        "Bare business words extracted from the question ('regional', "
        "'national') must still resolve to the matching group rules via "
        "fuzzy match against the group's display name."
    )
    assert len(res.applied_group_rules) == 2
    assert len(res.ignored_group_rules) == 0


def test_qui_a_acces_a_resolves_imprecise_group_against_acl():
    """
    Regression guard for the who_has_access_to half of the J4 Q6.1/Q6.2 bug:
    an imprecise group_id (short name, no module prefix) must resolve to
    the correct group via the same tolerant resolution used by
    evaluate_record_rules, not silently report false denial.
    """
    from code_intelligence.knowledge_rules.deterministic.access.access_evaluator import who_has_access_to

    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node(
        "access:test_acl",
        node_type="AccessEntry",
        perm_read=True,
    )
    G.add_edge("model:account.move", "access:test_acl", edge_type="GRANTED_BY")
    G.add_node(
        "group:custom_credit_note_visibility_rules.group_avoir_national",
        node_type="Group",
        name="Avoirs - Visibilite Nationale",
    )
    G.add_edge(
        "access:test_acl",
        "group:custom_credit_note_visibility_rules.group_avoir_national",
        edge_type="APPLIES_TO_GROUP",
    )

    res = who_has_access_to(G, "account.move", permission="read", group_id="group_national")
    assert "HAS READ access" in res.summary_text
    assert "DOES NOT HAVE" not in res.summary_text
    assert "could not be resolved" not in res.summary_text


def test_qui_a_acces_a_reports_unresolved_group_distinctly_from_denied():
    """
    A group_id that matches NOTHING (not even fuzzily) must be reported as
    unresolved, never as "DOES NOT HAVE access" -- the two are epistemically
    different and conflating them misrepresents an input problem as a
    security decision.
    """
    from code_intelligence.knowledge_rules.deterministic.access.access_evaluator import who_has_access_to

    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node("access:test_acl", node_type="AccessEntry", perm_read=True)
    G.add_edge("model:account.move", "access:test_acl", edge_type="GRANTED_BY")
    G.add_node(
        "group:account.group_account_manager",
        node_type="Group",
        name="Accounting Manager",
    )
    G.add_edge(
        "access:test_acl",
        "group:account.group_account_manager",
        edge_type="APPLIES_TO_GROUP",
    )

    res = who_has_access_to(G, "account.move", permission="read", group_id="xyz_totally_unrelated_gibberish")
    assert "could not be resolved" in res.summary_text
    assert "DOES NOT HAVE" not in res.summary_text


def test_implied_group_hierarchy_expansion_direction():
    """
    Validates that group hierarchy expansion via implied_ids correctly expands
    user groups along OUTGOING IMPLIES edges (Manager -> User):
      1. An user with group 'Manager' automatically gets 'User' (broader group).
      2. A record rule defined for 'User' correctly applies to the 'Manager' user.
      3. An user with group 'User' does NOT get 'Manager' (no false positive).
    """
    G = nx.DiGraph()

    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node("group:sales_team.group_sale_manager", node_type="Group", name="Sales Manager")
    G.add_node("group:sales_team.group_sale_salesman", node_type="Group", name="Sales User")

    # Manager --IMPLIES--> User (Manager has implied_ids = [User])
    G.add_edge("group:sales_team.group_sale_manager", "group:sales_team.group_sale_salesman", edge_type="IMPLIES")

    # Record rule targeted ONLY at 'User'
    G.add_node(
        "rule:sale.rule_user_only",
        node_type="Rule",
        name="User Only Rule",
        domain_force="[('user_id', '=', user.id)]",
        perm_read=True,
    )
    G.add_edge("model:account.move", "rule:sale.rule_user_only", edge_type="RESTRICTED_BY")
    G.add_edge("rule:sale.rule_user_only", "group:sales_team.group_sale_salesman", edge_type="APPLIES_TO_GROUP")

    # Case A: User assigned 'Manager' -> should get 'User' rule applied!
    res_mgr = evaluate_record_rules(G, "account.move", user_groups=["sales_team.group_sale_manager"])
    assert len(res_mgr.applied_group_rules) == 1
    assert res_mgr.applied_group_rules[0].rule_name == "User Only Rule"
    assert len(res_mgr.ignored_group_rules) == 0

    # Case B: User assigned 'User' -> does NOT get 'Manager' (no false positive higher privilege)
    res_usr = evaluate_record_rules(G, "account.move", user_groups=["sales_team.group_sale_salesman"])
    assert len(res_usr.applied_group_rules) == 1
    assert res_usr.applied_group_rules[0].rule_name == "User Only Rule"



def test_inactive_rule_is_excluded_from_graph():
    """
    Regression guard for J7 finding F-06: a rule with active=False in the
    source XML must not be included in the graph at all, since Odoo itself
    disables it -- evaluate_record_rules must never see it, let
    alone apply it as a phantom restriction.
    """
    import sys
    sys.path.insert(0, '.')
    from code_intelligence.knowledge_rules.graph import OdooGraphBuilder
    from code_intelligence.knowledge_rules.graph import ResolvedSymbolRegistry

    class _FakeRule:
        def __init__(self, xml_id, active):
            self.xml_id = xml_id
            self.name = "Fake Inactive Rule"
            self.domain_force = "[(1, '=', 1)]"
            self.filepath = "fake.xml"
            self.lineno = 1
            self.perm_read = True
            self.perm_write = True
            self.perm_create = True
            self.perm_unlink = True
            self.model_id = ""
            self.groups_id = []
            self.active = active

    registry = ResolvedSymbolRegistry()
    active_rule = _FakeRule("test_mod.rule_active", active=True)
    inactive_rule = _FakeRule("test_mod.rule_inactive", active=False)
    registry.rules["test_mod.rule_active"] = active_rule
    registry.rules["rule_active"] = active_rule
    registry.rules["test_mod.rule_inactive"] = inactive_rule
    registry.rules["rule_inactive"] = inactive_rule

    builder = OdooGraphBuilder(registry, {})
    G = builder.build_graph()

    assert "rule:test_mod.rule_active" in G
    assert "rule:test_mod.rule_inactive" not in G, (
        "A rule with active=False must be excluded from the graph entirely."
    )
