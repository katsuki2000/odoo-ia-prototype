"""
code_intelligence/tests/test_j23_24_authorization_gate.py

Unit tests for Bloc 7 / J23-J24: generalized gating -- every explanation is
filtered according to the demandeur's real rights (decision taken J22), with
an explicit "élément omis pour raison d'autorisation" state distinct from
sourcing verification (J14) and from the confidence/coverage score.
"""

import networkx as nx

from code_intelligence.authorization_gate import gate_observation, OmittedItem
from code_intelligence.deterministic_tools import (
    evaluer_regles_enregistrement,
    RuleDetail,
)


def _build_graph_with_acl(model_name: str, write_group: str) -> nx.DiGraph:
    """Minimal synthetic graph: one model with a WRITE-only ACL granted to
    write_group (no read/create/unlink), mirroring the ACL node shape used
    across the project's other deterministic_tools tests (see test_b1_1.py)."""
    G = nx.DiGraph()
    G.add_node(f"model:{model_name}", node_type="Model", name=model_name)
    G.add_node(
        f"acl:{model_name}.access_manager",
        node_type="AccessEntry",
        perm_read=True, perm_write=True, perm_create=True, perm_unlink=True,
        all_authenticated=False,
    )
    G.add_node(f"group:{write_group}", node_type="Group", name="Manager")
    G.add_edge(f"model:{model_name}", f"acl:{model_name}.access_manager", edge_type="GRANTED_BY")
    G.add_edge(f"acl:{model_name}.access_manager", f"group:{write_group}", edge_type="APPLIES_TO_GROUP")
    return G


def _build_graph_with_ir_rule(model_name: str, member_group: str, other_group: str) -> nx.DiGraph:
    """Model with two group-scoped ir.rule rules: one the demandeur is a
    member of, one they are not -- mirrors the ir.rule graph shape used in
    test_s2_1_record_rules.py."""
    G = nx.DiGraph()
    G.add_node(f"model:{model_name}", node_type="Model", name=model_name)
    G.add_node(
        f"rule:{model_name}.rule_member",
        node_type="Rule", name="Regle Membre",
        domain_force="[('amount','<=',1000)]", perm_read=True,
    )
    G.add_node(
        f"rule:{model_name}.rule_other",
        node_type="Rule", name="Regle Region Non Autorisee",
        domain_force="[('amount','<=',500000)]", perm_read=True,
    )
    G.add_node(f"group:{member_group}", node_type="Group", name="Membre")
    G.add_node(f"group:{other_group}", node_type="Group", name="Autre")
    G.add_edge(f"model:{model_name}", f"rule:{model_name}.rule_member", edge_type="RESTRICTED_BY")
    G.add_edge(f"rule:{model_name}.rule_member", f"group:{member_group}", edge_type="APPLIES_TO_GROUP")
    G.add_edge(f"model:{model_name}", f"rule:{model_name}.rule_other", edge_type="RESTRICTED_BY")
    G.add_edge(f"rule:{model_name}.rule_other", f"group:{other_group}", edge_type="APPLIES_TO_GROUP")
    return G


# ── Source 1: security-bypass tools (analyser_verrous_securite / analyser_actions_serveur) ──

def test_gated_tool_is_omitted_for_read_only_demandeur():
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    gated_text, omitted = gate_observation(
        tool_name="analyser_verrous_securite",
        model_name="account.move",
        observation="Hardcoded validators: [admin@corp.com]",
        G=G,
        user_groups=["some_other_group"],  # not a member of the write group
    )
    assert omitted is not None
    assert "account.move" in omitted.label
    assert "autorisation" in omitted.reason.lower()
    assert "admin@corp.com" not in gated_text
    assert "ÉLÉMENT OMIS POUR RAISON D'AUTORISATION" in gated_text


def test_gated_tool_is_not_omitted_for_elevated_demandeur():
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    gated_text, omitted = gate_observation(
        tool_name="analyser_verrous_securite",
        model_name="account.move",
        observation="Hardcoded validators: [admin@corp.com]",
        G=G,
        user_groups=["account.group_account_manager"],  # has write/unlink
    )
    assert omitted is None
    assert gated_text == "Hardcoded validators: [admin@corp.com]"


def test_gated_tool_all_authenticated_write_is_not_omitted():
    """An ACL granting write to all authenticated users means nobody is
    gated on that model -- everyone already has management-level access."""
    G = nx.DiGraph()
    G.add_node("model:helpdesk.ticket", node_type="Model", name="helpdesk.ticket")
    G.add_node(
        "acl:helpdesk.ticket.access_all",
        node_type="AccessEntry",
        perm_read=True, perm_write=True, perm_create=True, perm_unlink=False,
        all_authenticated=True,
    )
    G.add_edge("model:helpdesk.ticket", "acl:helpdesk.ticket.access_all", edge_type="GRANTED_BY")

    gated_text, omitted = gate_observation(
        tool_name="analyser_actions_serveur",
        model_name="helpdesk.ticket",
        observation="Server action bypasses approval via sudo().",
        G=G,
        user_groups=[],
    )
    assert omitted is None
    assert gated_text == "Server action bypasses approval via sudo()."


def test_non_gated_tool_name_passes_through_unchanged():
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    gated_text, omitted = gate_observation(
        tool_name="qui_a_acces_a",
        model_name="account.move",
        observation="Access matrix for account.move: ...",
        G=G,
        user_groups=[],
    )
    assert omitted is None
    assert gated_text == "Access matrix for account.move: ..."


# ── Source 2: ir.rule group rules the demandeur is not a member of ──

def test_ignored_group_rule_details_are_stripped():
    G = _build_graph_with_ir_rule(
        "custom.reimbursement.request",
        member_group="custom.group_reimbursement_member",
        other_group="custom.group_reimbursement_region_other",
    )
    rule_result = evaluer_regles_enregistrement(
        G, "custom.reimbursement.request", droit="read",
        user_groups=["custom.group_reimbursement_member"],
    )
    assert len(rule_result.ignored_group_rules) == 1

    gated_text, omitted = gate_observation(
        tool_name="evaluer_regles_enregistrement",
        model_name="custom.reimbursement.request",
        observation=rule_result.summary_text,
        G=G,
        user_groups=["custom.group_reimbursement_member"],
        rule_result=rule_result,
    )
    assert omitted is not None
    assert "Regle Region Non Autorisee" not in gated_text
    assert "500000" not in gated_text
    assert "ÉLÉMENT OMIS POUR RAISON D'AUTORISATION" in gated_text
    # The applicable rule the demandeur DOES belong to must remain visible.
    assert "Regle Membre" in gated_text


def test_no_ignored_rules_means_nothing_omitted():
    G = _build_graph_with_ir_rule(
        "custom.reimbursement.request",
        member_group="custom.group_reimbursement_member",
        other_group="custom.group_reimbursement_region_other",
    )
    # Demandeur belongs to BOTH groups -- nothing is ignored.
    rule_result = evaluer_regles_enregistrement(
        G, "custom.reimbursement.request", droit="read",
        user_groups=["custom.group_reimbursement_member", "custom.group_reimbursement_region_other"],
    )
    assert rule_result.ignored_group_rules == []

    gated_text, omitted = gate_observation(
        tool_name="evaluer_regles_enregistrement",
        model_name="custom.reimbursement.request",
        observation=rule_result.summary_text,
        G=G,
        user_groups=["custom.group_reimbursement_member", "custom.group_reimbursement_region_other"],
        rule_result=rule_result,
    )
    assert omitted is None
    assert gated_text == rule_result.summary_text


def test_evaluer_regles_without_rule_result_passes_through():
    """If rule_result wasn't computed (e.g. evaluer_regles_raw failed), the
    gate must not crash or fabricate an omission -- it must fail open on
    this specific defensive path, since the tool's own text already carries
    no privileged detail beyond what evaluer_regles_enregistrement prints."""
    G = _build_graph_with_ir_rule(
        "custom.reimbursement.request", "custom.group_a", "custom.group_b"
    )
    gated_text, omitted = gate_observation(
        tool_name="evaluer_regles_enregistrement",
        model_name="custom.reimbursement.request",
        observation="some summary text",
        G=G,
        user_groups=[],
        rule_result=None,
    )
    assert omitted is None
    assert gated_text == "some summary text"
