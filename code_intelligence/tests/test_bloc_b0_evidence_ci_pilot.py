"""
code_intelligence/tests/test_bloc_b0_evidence_ci_pilot.py

B0 pilot (todo/contexte.txt sections 426-428): validates that
evaluate_record_rules() produces structured Evidence at the source,
one per rule actually evaluated, instead of leaving the caller to parse
summary_text back into facts. This is the CI half of the B0 pilot pair
(ORM half: erp_data/tests/test_bloc_b0_evidence_orm_pilot.py) meant to
validate the Evidence contract end-to-end before replicating the pattern
across the remaining 11 CI actions + 9 ORM tools.
"""

import networkx as nx

from code_intelligence.deterministic.access.record_rules import evaluate_record_rules
from core.evidence import Evidence, EvidenceSourceType, stable_content_hash


def _build_test_graph() -> nx.DiGraph:
    """Same fixture shape as test_s2_1_record_rules.py's Adversarial
    Module 8 (custom_credit_note_visibility_rules) -- reused rather than
    duplicated, since it already exercises global + applied group + ignored
    group in a single evaluation."""
    G = nx.DiGraph()

    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node(
        "group:custom_credit_note_visibility_rules.group_regional",
        node_type="Group", name="Avoirs - Visibilité Régionale",
        xml_id="custom_credit_note_visibility_rules.group_regional",
    )
    G.add_node(
        "group:custom_credit_note_visibility_rules.group_national",
        node_type="Group", name="Avoirs - Visibilité Nationale",
        xml_id="custom_credit_note_visibility_rules.group_national",
    )

    G.add_node(
        "rule:custom_credit_note_visibility_rules.rule_global_multi_company",
        node_type="Rule", name="Avoirs Global Multi-Company",
        xml_id="custom_credit_note_visibility_rules.rule_global_multi_company",
        domain_force="[('company_id', 'in', company_ids)]", perm_read=True,
    )
    G.add_edge(
        "model:account.move",
        "rule:custom_credit_note_visibility_rules.rule_global_multi_company",
        edge_type="RESTRICTED_BY",
    )

    G.add_node(
        "rule:custom_credit_note_visibility_rules.rule_regional_limit",
        node_type="Rule", name="Avoirs Régionaux Plafond 50k",
        xml_id="custom_credit_note_visibility_rules.rule_regional_limit",
        domain_force="[('amount_total', '<=', 50000)]", perm_read=True,
    )
    G.add_edge(
        "model:account.move",
        "rule:custom_credit_note_visibility_rules.rule_regional_limit",
        edge_type="RESTRICTED_BY",
    )
    G.add_edge(
        "rule:custom_credit_note_visibility_rules.rule_regional_limit",
        "group:custom_credit_note_visibility_rules.group_regional",
        edge_type="APPLIES_TO_GROUP",
    )

    G.add_node(
        "rule:custom_credit_note_visibility_rules.rule_national_unlimited",
        node_type="Rule", name="Avoirs Nationaux Illimités",
        xml_id="custom_credit_note_visibility_rules.rule_national_unlimited",
        domain_force="[(1, '=', 1)]", perm_read=True,
    )
    G.add_edge(
        "model:account.move",
        "rule:custom_credit_note_visibility_rules.rule_national_unlimited",
        edge_type="RESTRICTED_BY",
    )
    G.add_edge(
        "rule:custom_credit_note_visibility_rules.rule_national_unlimited",
        "group:custom_credit_note_visibility_rules.group_national",
        edge_type="APPLIES_TO_GROUP",
    )

    return G


def test_evidence_count_matches_evaluated_rules():
    """One Evidence per rule actually evaluated: 1 global + 1 applied group
    (regional) + 1 ignored group (national) for a regional-only user."""
    G = _build_test_graph()
    res = evaluate_record_rules(
        G, "account.move",
        user_groups=["custom_credit_note_visibility_rules.group_regional"],
    )
    assert len(res.evidence) == 3
    assert all(isinstance(e, Evidence) for e in res.evidence)


def test_evidence_source_type_and_confidence():
    """CI evidence is CODE-sourced and marked HIGH confidence: this is a
    deterministic graph read, not an LLM-interpreted heuristic."""
    G = _build_test_graph()
    res = evaluate_record_rules(
        G, "account.move",
        user_groups=["custom_credit_note_visibility_rules.group_national"],
    )
    for e in res.evidence:
        assert e.source_type == EvidenceSourceType.CODE
        assert e.confidence == "HIGH"
        assert e.source.startswith("rule:")


def test_evidence_scope_carries_user_groups():
    """scope must carry the requester's groups, since a rule's
    applied/ignored status depends on them -- the claim itself stays
    group-agnostic (deterministic given the graph), the context goes in
    scope per B0's decision (todo/contexte.txt section 426)."""
    G = _build_test_graph()
    groups = ["custom_credit_note_visibility_rules.group_national"]
    res = evaluate_record_rules(G, "account.move", user_groups=groups)
    for e in res.evidence:
        assert e.scope["user_groups"] == sorted(groups)


def test_evidence_id_is_deterministic_across_runs():
    """Same inputs -> same evidence_id across two independent evaluations
    (no hidden state, no random UUID)."""
    G = _build_test_graph()
    groups = ["custom_credit_note_visibility_rules.group_regional"]

    res1 = evaluate_record_rules(G, "account.move", user_groups=groups)
    res2 = evaluate_record_rules(G, "account.move", user_groups=groups)

    ids1 = sorted(e.evidence_id for e in res1.evidence)
    ids2 = sorted(e.evidence_id for e in res2.evidence)
    assert ids1 == ids2


def test_evidence_id_differs_when_user_groups_differ():
    """Same rule set, different requester groups -> different evidence_id,
    since scope (user_groups) is part of the hashed payload and the
    applied/ignored bucket a rule falls into genuinely changes."""
    G = _build_test_graph()

    res_regional = evaluate_record_rules(
        G, "account.move",
        user_groups=["custom_credit_note_visibility_rules.group_regional"],
    )
    res_national = evaluate_record_rules(
        G, "account.move",
        user_groups=["custom_credit_note_visibility_rules.group_national"],
    )

    regional_rule_evidence = next(
        e for e in res_regional.evidence if "rule_regional_limit" in e.source
    )
    national_rule_evidence = next(
        e for e in res_national.evidence if "rule_regional_limit" in e.source
    )
    assert regional_rule_evidence.evidence_id != national_rule_evidence.evidence_id


def test_stable_content_hash_ignores_scope_key_order():
    """Canonicalization requirement (todo/contexte.txt section 428): two
    scope dicts with the same keys in a different insertion order must
    hash identically."""
    h1 = stable_content_hash(
        EvidenceSourceType.CODE, "claim", "value", "source",
        {"a": 1, "b": 2},
    )
    h2 = stable_content_hash(
        EvidenceSourceType.CODE, "claim", "value", "source",
        {"b": 2, "a": 1},
    )
    assert h1 == h2
