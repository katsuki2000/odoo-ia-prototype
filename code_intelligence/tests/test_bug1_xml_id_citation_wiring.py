"""
code_intelligence/tests/test_bug1_xml_id_citation_wiring.py

Bug 1 (todo/contexte.txt section 490, option A): end-to-end regression for
the sourcing_guard xml_id wiring. Unlike test_j14_sourcing_guard.py (which
feeds hand-written raw/answer strings directly to verify_citations()), this
file exercises the actual tool formatters (deterministic_tools.py,
server_action_analyzer.py) so a regression that removes the 'xml_id: '
prefix from a tool's own output -- not just from sourcing_guard.py itself --
is caught. Chain covered: tool output (summary_text/execution_steps) ->
ground_truth_xml_ids (verify_citations' own extraction) -> a simulated LLM
citation copied verbatim -> verify_citations().
"""

import networkx as nx

from code_intelligence.deterministic_tools import (
    evaluate_record_rules,
    who_has_access_to,
)
from code_intelligence.server_action_analyzer import analyze_server_action_code
from code_intelligence.sourcing_guard import verify_citations


def _build_test_graph() -> nx.DiGraph:
    """Same fixture shape as test_bloc_b1_evidence_who_has_access_to.py --
    reused rather than duplicated (F-08)."""
    G = nx.DiGraph()

    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node(
        "acl:sale.access_user", node_type="AccessEntry",
        perm_read=True, perm_write=True, perm_create=True, perm_unlink=False,
        all_authenticated=False,
    )
    G.add_node("group:sales_team.group_sale_salesman", node_type="Group", name="User")
    G.add_node(
        "rule:sale.rule_user", node_type="Rule", name="User Rule",
        domain_force="[('user_id','=',user.id)]", perm_read=True, perm_write=True,
    )

    G.add_edge("model:sale.order", "acl:sale.access_user", edge_type="GRANTED_BY")
    G.add_edge("acl:sale.access_user", "group:sales_team.group_sale_salesman", edge_type="APPLIES_TO_GROUP")
    G.add_edge("model:sale.order", "rule:sale.rule_user", edge_type="RESTRICTED_BY")
    G.add_edge("rule:sale.rule_user", "group:sales_team.group_sale_salesman", edge_type="APPLIES_TO_GROUP")

    return G


def test_evaluate_record_rules_output_carries_verifiable_xml_id():
    """The rule_xml_id evaluate_record_rules names in its own summary_text
    must itself be extractable as ground truth by sourcing_guard -- a
    synthesis LLM copying it verbatim must pass verification."""
    G = _build_test_graph()
    result = evaluate_record_rules(G, "sale.order", permission="read", user_groups=["sales_team.group_sale_salesman"])

    assert "xml_id: sale.rule_user" in result.summary_text

    simulated_answer = "Accès conditionné par la règle (xml_id: sale.rule_user)."
    verification = verify_citations(simulated_answer, result.summary_text)
    assert verification.is_fully_verified
    assert not verification.unverified_xml_ids


def test_evaluate_record_rules_flags_fabricated_xml_id():
    """A citation the LLM invents (not present in the tool's own output)
    must still be flagged, even though the tool's real output is now
    correctly citable -- this is the negative-control counterpart to the
    happy path above."""
    G = _build_test_graph()
    result = evaluate_record_rules(G, "sale.order", permission="read", user_groups=["sales_team.group_sale_salesman"])

    simulated_answer = "Accès conditionné par (xml_id: invented_module.not_a_real_rule)."
    verification = verify_citations(simulated_answer, result.summary_text)
    assert not verification.is_fully_verified
    assert "invented_module.not_a_real_rule" in verification.unverified_xml_ids


def test_who_has_access_to_group_id_output_carries_verifiable_xml_id():
    """group_id-scoped who_has_access_to branch: the resolved group xml_id
    must be citable the same way."""
    G = _build_test_graph()
    result = who_has_access_to(G, "sale.order", permission="read", group_id="sales_team.group_sale_salesman")

    assert "xml_id: sales_team.group_sale_salesman" in result.summary_text

    simulated_answer = "Le groupe a accès (xml_id: sales_team.group_sale_salesman)."
    verification = verify_citations(simulated_answer, result.summary_text)
    assert verification.is_fully_verified


def test_who_has_access_to_all_permissions_output_carries_verifiable_xml_id():
    """permission='all' branch builds its own citation suffix separately
    (list of groups per permission row) -- must not regress independently
    of the single-permission branch."""
    G = _build_test_graph()
    result = who_has_access_to(G, "sale.order", permission="all")

    assert "xml_id: sales_team.group_sale_salesman" in result.summary_text

    simulated_answer = "Droits accordés (xml_id: sales_team.group_sale_salesman)."
    verification = verify_citations(simulated_answer, result.summary_text)
    assert verification.is_fully_verified


def test_analyze_server_action_code_output_carries_verifiable_xml_id():
    """analyze_server_action_code (Analyse CI, not a Composite) must emit
    the same citation format for its own action_xml_id."""
    result = analyze_server_action_code(
        code="if user.has_group('base.group_system'):\n    record.sudo().write({'state': 'done'})",
        action_xml_id="custom_module.action_force_done",
    )

    assert "xml_id: custom_module.action_force_done" in result.summary_text

    simulated_answer = "Cette action (xml_id: custom_module.action_force_done) contourne les droits."
    verification = verify_citations(simulated_answer, result.summary_text)
    assert verification.is_fully_verified
