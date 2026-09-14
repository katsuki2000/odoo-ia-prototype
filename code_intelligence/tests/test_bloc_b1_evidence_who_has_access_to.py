"""
code_intelligence/tests/test_bloc_b1_evidence_who_has_access_to.py

B1 replication of the B0 pilot (todo/contexte.txt sections 426-440):
validates that who_has_access_to() produces structured Evidence at the
source, for the ACL grant fact and each active ir.rule found, for both
the single-permission and 'all'-permission code paths. First of the 5
composite CI tools in the retained order (composites -> analyse -> aux ->
ORM, section 440).
"""

import networkx as nx

from code_intelligence.rules.access_evaluator import who_has_access_to
from core.evidence.evidence import Evidence, EvidenceSourceType


def _build_test_graph() -> nx.DiGraph:
    """Same fixture shape as test_b1_1.py::test_qui_a_acces_a_synthetic --
    reused rather than duplicated, already exercises ACL + group hierarchy
    (IMPLIES) + one active ir.rule in a single graph."""
    G = nx.DiGraph()

    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node(
        "acl:sale.access_user", node_type="AccessEntry",
        perm_read=True, perm_write=True, perm_create=True, perm_unlink=False,
        all_authenticated=False,
    )
    G.add_node("group:sales_team.group_sale_salesman", node_type="Group", name="User")
    G.add_node("group:sales_team.group_sale_manager", node_type="Group", name="Manager")
    G.add_node(
        "rule:sale.rule_user", node_type="Rule", name="User Rule",
        domain_force="[('user_id','=',user.id)]", perm_read=True, perm_write=True,
    )

    G.add_edge("model:sale.order", "acl:sale.access_user", edge_type="GRANTED_BY")
    G.add_edge("acl:sale.access_user", "group:sales_team.group_sale_salesman", edge_type="APPLIES_TO_GROUP")
    G.add_edge("group:sales_team.group_sale_manager", "group:sales_team.group_sale_salesman", edge_type="IMPLIES")
    G.add_edge("model:sale.order", "rule:sale.rule_user", edge_type="RESTRICTED_BY")
    G.add_edge("rule:sale.rule_user", "group:sales_team.group_sale_salesman", edge_type="APPLIES_TO_GROUP")

    return G


def test_evidence_count_single_permission_with_active_rule():
    """1 ACL-grant Evidence + 1 per active rule (here: 1) for a single
    permission query with results."""
    G = _build_test_graph()
    res = who_has_access_to(G, "sale.order", permission="read")
    assert len(res.evidence) == 2
    assert all(isinstance(e, Evidence) for e in res.evidence)


def test_evidence_source_type_and_confidence():
    """CI evidence is CODE-sourced and marked HIGH confidence, same
    vocabulary as the evaluate_record_rules pilot."""
    G = _build_test_graph()
    res = who_has_access_to(G, "sale.order", permission="read")
    for e in res.evidence:
        assert e.source_type == EvidenceSourceType.CODE
        assert e.confidence == "HIGH"


def test_evidence_no_acl_grant_still_produces_a_fact():
    """unlink is not granted by the ACL in the fixture -- must still
    produce an explicit 'no ACL grants' Evidence, not silence. The rule
    in the fixture carries no explicit perm_unlink attribute, and
    _eval_single_permission()'s own convention (rule_node.get(perm_attr,
    True), same default used by evaluate_record_rules) treats a missing
    perm_* attribute as active for that permission -- so a rule-restriction
    Evidence is expected here too, not just the ACL one."""
    G = _build_test_graph()
    res = who_has_access_to(G, "sale.order", permission="unlink")
    assert len(res.evidence) == 2
    assert "No ACL explicitly grants" in res.evidence[0].claim
    assert res.evidence[0].value is None
    assert "can further restrict" in res.evidence[1].claim


def test_evidence_all_permissions_aggregates_across_four_perms():
    """permission='all' must produce Evidence for each of the 4
    permissions evaluated, not just the last one iterated. The fixture's
    single rule carries no explicit perm_create/perm_unlink attribute, so
    (same default as evaluate_record_rules) it is active for all 4
    permissions: 1 ACL-fact + 1 rule-fact per permission = 8 total."""
    G = _build_test_graph()
    res = who_has_access_to(G, "sale.order", permission="all")
    sources = [e.source for e in res.evidence]
    assert any(":read" in s for s in sources)
    assert any(":write" in s for s in sources)
    assert any(":create" in s for s in sources)
    assert any(":unlink" in s for s in sources)
    assert len(res.evidence) == 8


def test_evidence_scope_carries_group_id_when_narrowed():
    """A group_id-narrowed query must carry that group_id in scope, since
    the ACL/rule facts are otherwise requester-agnostic."""
    G = _build_test_graph()
    res = who_has_access_to(
        G, "sale.order", permission="write",
        group_id="sales_team.group_sale_manager",
    )
    for e in res.evidence:
        assert e.scope.get("group_id") == "sales_team.group_sale_manager"


def test_evidence_scope_empty_when_not_narrowed():
    """No group_id supplied -> no group_id key in scope (never a
    fabricated/decorative default)."""
    G = _build_test_graph()
    res = who_has_access_to(G, "sale.order", permission="read")
    for e in res.evidence:
        assert "group_id" not in e.scope


def test_evidence_id_is_deterministic_across_runs():
    """Same inputs -> same evidence_id across two independent calls."""
    G = _build_test_graph()
    res1 = who_has_access_to(G, "sale.order", permission="read")
    res2 = who_has_access_to(G, "sale.order", permission="read")
    ids1 = sorted(e.evidence_id for e in res1.evidence)
    ids2 = sorted(e.evidence_id for e in res2.evidence)
    assert ids1 == ids2


def test_model_not_found_produces_no_evidence():
    """A model absent from the graph returns the existing NOT_FOUND
    summary_text and an empty evidence list -- never a fabricated fact."""
    G = _build_test_graph()
    res = who_has_access_to(G, "does.not.exist", permission="read")
    assert res.evidence == []
