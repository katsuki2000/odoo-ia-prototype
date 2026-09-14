"""
code_intelligence/tests/test_j23_24_authorization_gate.py

Unit tests for  / J23-J24 (REVISED twice, see authorization_gate.py
module docstring):

  1. TARGETED gating -- only lines explicitly tagged SENSITIVE_BYPASS_MARKER
     at the source are redacted, never a whole tool observation. Governance
     content (normal approval groups, has_group() checks, uncertainty
     caveats) must always survive gating untouched, even for a demandeur
     without elevated access -- that's precisely the bug this revision
     fixes (see git history / real   J23-24 for the original
     generalized-gating regression found in the first benchmark run).

  2. (2026-08-07) ir.rule group rules the demandeur is NOT a member of are
     no longer redacted by membership -- their name and domain_force are
     governance/scoping content ("who can see what under which regional/
     national cap"), the same category as "qui peut approuver ?", not a
     security bypass. Only SENSITIVE_BYPASS_MARKER-tagged content is still
     identity-gated.

An explicit "élément omis pour raison d'autorisation" state is still kept,
distinct from sourcing verification  and from the confidence/coverage
score, for the one remaining gated source (SENSITIVE_BYPASS_MARKER).
"""

import networkx as nx

from code_intelligence.rules.security_locks import gate_observation, OmittedItem
from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
from code_intelligence.rules.record_rules import evaluate_record_rules
from code_intelligence.rules.record_rules import RuleDetail


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


# ── Source 1: lines tagged SENSITIVE_BYPASS_MARKER at the source ──

def test_marked_bypass_line_is_redacted_for_read_only_demandeur():
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    observation = (
        f"Analyse des verrous Python [Confiance: HIGH]:\n"
        f"  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilegies en dur: ['admin@corp.com']"
    )
    gated_text, omitted = gate_observation(
        tool_name="analyze_security_locks",
        model_name="account.move",
        observation=observation,
        G=G,
        user_groups=["some_other_group"],  # not a member of the write group
    )
    assert len(omitted) == 1
    assert "account.move" in omitted[0].label
    assert "autorisation" in omitted[0].reason.lower()
    assert "admin@corp.com" not in gated_text
    assert "ELEMENT OMITTED FOR AUTHORIZATION REASON" in gated_text
    # The header line (no marker) must survive untouched.
    assert "Analyse des verrous Python [Confiance: HIGH]:" in gated_text


def test_marked_bypass_line_is_not_redacted_for_elevated_demandeur():
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    observation = f"  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilegies en dur: ['admin@corp.com']"
    gated_text, omitted = gate_observation(
        tool_name="analyze_security_locks",
        model_name="account.move",
        observation=observation,
        G=G,
        user_groups=["account.group_account_manager"],  # has write/unlink
    )
    assert omitted == []
    assert gated_text == observation


def test_unmarked_governance_content_is_never_redacted():
    """Core regression lock for the J23-24 revision: ordinary governance
    lines (which groups can approve, has_group() checks) carry no marker
    and must stay fully visible even to a demandeur with zero elevated
    access -- this is exactly what broke basic 'qui peut approuver ?'
    questions under the original generalized-gating design."""
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    observation = (
        "Analyse du code de l'action serveur 'approve_credit_note' "
        "[Confiance: FAIBLE]:\n"
        "  - Vérifications de groupes: account.group_account_manager\n"
        "  - Dispatch dynamique: getattr → comportement non classifiable statiquement"
    )
    gated_text, omitted = gate_observation(
        tool_name="analyze_server_actions",
        model_name="account.move",
        observation=observation,
        G=G,
        user_groups=[],  # zero access at all
    )
    assert omitted == []
    assert gated_text == observation


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

    observation = f"  - {SENSITIVE_BYPASS_MARKER} SUDO détecté: Contournement des droits d'accès via sudo()"
    gated_text, omitted = gate_observation(
        tool_name="analyze_server_actions",
        model_name="helpdesk.ticket",
        observation=observation,
        G=G,
        user_groups=[],
    )
    assert omitted == []
    assert gated_text == observation


def test_no_marker_means_nothing_omitted_regardless_of_tool_name():
    """Marker-based redaction is tool-name-agnostic: any tool's output is
    left untouched as long as it carries no SENSITIVE_BYPASS_MARKER line --
    no allowlist of "gated tool names" exists anymore."""
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    gated_text, omitted = gate_observation(
        tool_name="who_has_access_to",
        model_name="account.move",
        observation="Access matrix for account.move: ...",
        G=G,
        user_groups=[],
    )
    assert omitted == []
    assert gated_text == "Access matrix for account.move: ..."


# ── Source 2 (removed 2026-08-07): ir.rule group rules the demandeur is ──
# ── not a member of are governance content and are never redacted now ──

def test_ignored_group_rule_details_are_never_redacted():
    """Regression lock for the 2026-08-07 revision: a rule name and its
    domain_force (e.g. a regional visibility cap) must survive gating even
    for a demandeur who is not a member of the group that rule targets --
    this is exactly the same category of content as "qui peut approuver ?",
    which Source 1's tests above already established must never be gated.
    """
    G = _build_graph_with_ir_rule(
        "custom.reimbursement.request",
        member_group="custom.group_reimbursement_member",
        other_group="custom.group_reimbursement_region_other",
    )
    rule_result = evaluate_record_rules(
        G, "custom.reimbursement.request", permission="read",
        user_groups=["custom.group_reimbursement_member"],
    )
    assert len(rule_result.ignored_group_rules) == 1

    gated_text, omitted = gate_observation(
        tool_name="evaluate_record_rules",
        model_name="custom.reimbursement.request",
        observation=rule_result.summary_text,
        G=G,
        user_groups=["custom.group_reimbursement_member"],
        rule_result=rule_result,
    )
    assert omitted == []
    assert "Regle Region Non Autorisee" in gated_text
    assert "500000" in gated_text
    assert "ELEMENT OMITTED FOR AUTHORIZATION REASON" not in gated_text
    # The applicable rule the demandeur DOES belong to must remain visible too.
    assert "Regle Membre" in gated_text
    assert gated_text == rule_result.summary_text


def test_no_ignored_rules_means_nothing_omitted():
    G = _build_graph_with_ir_rule(
        "custom.reimbursement.request",
        member_group="custom.group_reimbursement_member",
        other_group="custom.group_reimbursement_region_other",
    )
    # Demandeur belongs to BOTH groups -- nothing is ignored.
    rule_result = evaluate_record_rules(
        G, "custom.reimbursement.request", permission="read",
        user_groups=["custom.group_reimbursement_member", "custom.group_reimbursement_region_other"],
    )
    assert rule_result.ignored_group_rules == []

    gated_text, omitted = gate_observation(
        tool_name="evaluate_record_rules",
        model_name="custom.reimbursement.request",
        observation=rule_result.summary_text,
        G=G,
        user_groups=["custom.group_reimbursement_member", "custom.group_reimbursement_region_other"],
        rule_result=rule_result,
    )
    assert omitted == []
    assert gated_text == rule_result.summary_text


def test_evaluer_regles_without_rule_result_passes_through():
    """If rule_result wasn't computed (e.g. evaluate_rules_raw failed), the
    gate must not crash or fabricate an omission -- it must fail open on
    this specific defensive path, since the tool's own text already carries
    no privileged detail beyond what evaluate_record_rules prints."""
    G = _build_graph_with_ir_rule(
        "custom.reimbursement.request", "custom.group_a", "custom.group_b"
    )
    gated_text, omitted = gate_observation(
        tool_name="evaluate_record_rules",
        model_name="custom.reimbursement.request",
        observation="some summary text",
        G=G,
        user_groups=[],
        rule_result=None,
    )
    assert omitted == []
    assert gated_text == "some summary text"
