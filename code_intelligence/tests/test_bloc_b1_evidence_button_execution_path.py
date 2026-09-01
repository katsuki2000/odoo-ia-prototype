"""
code_intelligence/tests/test_bloc_b1_evidence_button_execution_path.py

B1 replication of the B0 pilot (todo/contexte.txt sections 426-444):
validates that button_execution_path() produces structured Evidence at
the source -- method invocation, state transition (or its absence),
button-level security requirement (or its absence), and requester
availability when user_groups is supplied. Third of the 5 composite CI
tools in the retained order (composites -> analyse -> aux -> ORM,
section 440); who_has_access_to (1/24) and field_change_impact (2/24)
closed in sections 442/444.
"""

import networkx as nx

from code_intelligence.deterministic_tools import button_execution_path
from core.evidence import Evidence, EvidenceSourceType


def _build_test_graph(model_name: str, required_groups=None) -> nx.DiGraph:
    """Same fixture shape as test_j22bis_button_availability_gate.py's
    _build_graph_with_button -- one workflow transition button (Valider:
    draft -> validated) -- reused rather than duplicated."""
    G = nx.DiGraph()
    G.add_node(f"model:{model_name}", node_type="Model", name=model_name)
    G.add_node(
        f"method:{model_name}.action_valider_avoir",
        node_type="Method", name="action_valider_avoir", model=model_name,
    )
    G.add_node(f"state:{model_name}.draft", node_type="WorkflowState", model=model_name, state_value="draft")
    G.add_node(f"state:{model_name}.validated", node_type="WorkflowState", model=model_name, state_value="validated")

    G.add_edge(
        f"state:{model_name}.draft",
        f"state:{model_name}.validated",
        edge_type="TRANSITIONS_VIA",
        method_name="action_valider_avoir",
        label_bouton="Valider",
        groupe_requis=required_groups or [],
    )
    return G


def test_evidence_count_with_transition_required_groups_and_user_groups():
    """4 facts when there IS a transition, required groups, and
    user_groups is supplied: method + transition + security + availability."""
    G = _build_test_graph("account.move", required_groups=["account.group_account_manager"])
    res = button_execution_path(
        G, "Valider", "account.move",
        user_groups=["account.group_account_manager"],
    )
    assert len(res.evidence) == 4
    assert all(isinstance(e, Evidence) for e in res.evidence)
    sources = [e.source for e in res.evidence]
    assert "method:account.move.action_valider_avoir" in sources
    assert "transition:account.move:action_valider_avoir" in sources
    assert "button_security:account.move:action_valider_avoir" in sources
    assert "button_availability:account.move:action_valider_avoir" in sources


def test_evidence_source_type_and_confidence():
    G = _build_test_graph("account.move", required_groups=["account.group_account_manager"])
    res = button_execution_path(
        G, "Valider", "account.move",
        user_groups=["account.group_account_manager"],
    )
    for e in res.evidence:
        assert e.source_type == EvidenceSourceType.CODE
        assert e.confidence == "HIGH"


def test_evidence_no_user_groups_produces_three_facts_no_availability():
    """user_groups=None (existing callers' default) -- only the three
    requester-agnostic structural facts, no availability fact."""
    G = _build_test_graph("account.move", required_groups=["account.group_account_manager"])
    res = button_execution_path(G, "Valider", "account.move")
    assert len(res.evidence) == 3
    assert not any(e.source.startswith("button_availability:") for e in res.evidence)


def test_evidence_no_required_groups_produces_explicit_no_restriction_fact():
    """No button-level restriction must still produce an explicit fact,
    not silence -- same convention as who_has_access_to's ACL branch."""
    G = _build_test_graph("account.move", required_groups=[])
    res = button_execution_path(G, "Valider", "account.move")
    e = next(ev for ev in res.evidence if ev.source == "button_security:account.move:action_valider_avoir")
    assert "carries no button-level group restriction" in e.claim
    assert e.value is None


def test_evidence_availability_scope_carries_user_groups():
    """The availability fact is requester-specific -- scope must carry the
    resolved user_groups, unlike the other three facts."""
    G = _build_test_graph("account.move", required_groups=["account.group_account_manager"])
    res = button_execution_path(
        G, "Valider", "account.move",
        user_groups=["base.group_user"],
    )
    availability_evidence = next(e for e in res.evidence if e.source.startswith("button_availability:"))
    assert availability_evidence.scope == {"user_groups": ["base.group_user"]}
    assert availability_evidence.value is False
    for e in res.evidence:
        if not e.source.startswith("button_availability:"):
            assert e.scope == {}


def test_evidence_transition_value_and_claim():
    G = _build_test_graph("account.move", required_groups=[])
    res = button_execution_path(G, "Valider", "account.move")
    e = next(ev for ev in res.evidence if ev.source == "transition:account.move:action_valider_avoir")
    assert e.value == "validated"
    assert "from [draft] to 'validated'" in e.claim


def test_evidence_no_transition_found_when_button_label_does_not_match():
    """A button label that matches no TRANSITIONS_VIA edge must still
    produce an explicit 'no transition' fact, never silence."""
    G = _build_test_graph("account.move", required_groups=[])
    res = button_execution_path(G, "UnrelatedLabel", "account.move")
    e = next(ev for ev in res.evidence if ev.source.startswith("transition:"))
    assert e.value is None
    assert "triggers no workflow state transition" in e.claim


def test_evidence_id_is_deterministic_across_runs():
    G = _build_test_graph("account.move", required_groups=["account.group_account_manager"])
    res1 = button_execution_path(G, "Valider", "account.move", user_groups=["account.group_account_manager"])
    res2 = button_execution_path(G, "Valider", "account.move", user_groups=["account.group_account_manager"])
    ids1 = sorted(e.evidence_id for e in res1.evidence)
    ids2 = sorted(e.evidence_id for e in res2.evidence)
    assert ids1 == ids2


def test_model_not_found_produces_no_evidence():
    G = _build_test_graph("account.move", required_groups=[])
    res = button_execution_path(G, "Valider", "does.not.exist")
    assert res.evidence == []
