"""
code_intelligence/tests/test_bloc_b1_evidence_describe_workflow.py

B1 replication of the B0 pilot (todo/contexte.txt sections 426-447):
validates that describe_workflow() produces structured Evidence at the
source -- one per TRANSITIONS_VIA edge found, or a single explicit "no
transitions" fact when the model carries no workflow state machine at
all. Last of the 5 composite CI tools in the retained order (composites
-> analyse -> aux -> ORM, section 440); trace_full_inheritance (4/24)
closed in section 448.
"""

import networkx as nx

from code_intelligence.knowledge_rules.deterministic.structure.workflow_process import describe_workflow
from code_intelligence.knowledge_rules.deterministic.common import QueryStatus
from core.evidence.evidence import Evidence, EvidenceSourceType


def _build_test_graph() -> nx.DiGraph:
    """Synthetic graph, hand-built, covering all 3 branches:
      - 'hr.expense' has 2 workflow states and 2 TRANSITIONS_VIA edges,
        one restricted to a group (draft -> submitted, no restriction;
        submitted -> approved, restricted to group_hr_manager) --
        exercises both the plain and the group-restricted claim shape.
      - 'hr.leave' exists as a model node but has no WorkflowState/
        TRANSITIONS_VIA edges at all -- exercises the explicit "no
        transitions" fact (EMPTY status).
      - 'model.missing' is never added as a node -- exercises the
        NOT_FOUND branch (empty evidence, no fabricated fact).
    """
    G = nx.DiGraph()

    G.add_node("model:hr.expense", node_type="Model")
    G.add_node("model:hr.leave", node_type="Model")

    G.add_node("state:hr.expense.draft", node_type="WorkflowState", model="hr.expense", state_value="draft")
    G.add_node("state:hr.expense.submitted", node_type="WorkflowState", model="hr.expense", state_value="submitted")
    G.add_node("state:hr.expense.approved", node_type="WorkflowState", model="hr.expense", state_value="approved")

    G.add_edge(
        "state:hr.expense.draft", "state:hr.expense.submitted",
        edge_type="TRANSITIONS_VIA", method_name="action_submit",
        label_bouton="Soumettre", groupe_requis=[],
    )
    G.add_edge(
        "state:hr.expense.submitted", "state:hr.expense.approved",
        edge_type="TRANSITIONS_VIA", method_name="action_approve",
        label_bouton="Valider", groupe_requis=["group_hr_manager"],
    )

    return G


def test_evidence_count_matches_transitions():
    """2 TRANSITIONS_VIA edges = 2 Evidence, no 'no transitions' fact."""
    G = _build_test_graph()
    res = describe_workflow(G, "hr.expense")
    assert res.status == QueryStatus.FOUND
    assert len(res.evidence) == 2
    assert all(isinstance(e, Evidence) for e in res.evidence)


def test_evidence_source_type_and_confidence():
    """CI evidence is CODE-sourced and marked HIGH confidence, same
    vocabulary as the B0/B1 precedents."""
    G = _build_test_graph()
    res = describe_workflow(G, "hr.expense")
    for e in res.evidence:
        assert e.source_type == EvidenceSourceType.CODE
        assert e.confidence == "HIGH"


def test_evidence_unrestricted_transition_claim_and_value():
    """draft -> submitted carries no required_groups -- value is the
    target state, claim mentions no group restriction."""
    G = _build_test_graph()
    res = describe_workflow(G, "hr.expense")
    e = next(ev for ev in res.evidence if ev.source == "transition:hr.expense:action_submit:draft:submitted")
    assert e.value == "submitted"
    assert "transitions from 'draft' to 'submitted'" in e.claim
    assert "via button 'Soumettre'" in e.claim
    assert "restricted to groups" not in e.claim


def test_evidence_restricted_transition_claim_mentions_groups():
    """submitted -> approved is restricted to group_hr_manager -- the
    claim must surface the restriction explicitly."""
    G = _build_test_graph()
    res = describe_workflow(G, "hr.expense")
    e = next(ev for ev in res.evidence if ev.source == "transition:hr.expense:action_approve:submitted:approved")
    assert e.value == "approved"
    assert "restricted to groups: group_hr_manager" in e.claim


def test_evidence_no_transitions_produces_explicit_fact():
    """A model with no WorkflowState/TRANSITIONS_VIA edges (EMPTY status)
    still asserts one explicit negative fact -- never silently empty."""
    G = _build_test_graph()
    res = describe_workflow(G, "hr.leave")
    assert res.status == QueryStatus.EMPTY
    assert len(res.evidence) == 1
    e = res.evidence[0]
    assert e.source == "workflow:hr.leave"
    assert e.value is None
    assert "no explicit workflow state transitions defined" in e.claim


def test_evidence_scope_is_always_empty():
    """No requester context for a structural workflow fact (describe_workflow
    takes no user_groups param) -- scope must stay {} on every Evidence,
    both models."""
    G = _build_test_graph()
    for model in ("hr.expense", "hr.leave"):
        res = describe_workflow(G, model)
        for e in res.evidence:
            assert e.scope == {}


def test_evidence_id_is_deterministic_across_runs():
    """Same inputs -> same evidence_id across two independent calls."""
    G = _build_test_graph()
    res1 = describe_workflow(G, "hr.expense")
    res2 = describe_workflow(G, "hr.expense")
    ids1 = sorted(e.evidence_id for e in res1.evidence)
    ids2 = sorted(e.evidence_id for e in res2.evidence)
    assert ids1 == ids2


def test_model_not_found_produces_no_evidence():
    """A model absent from the graph returns the existing NOT_FOUND
    summary_text and an empty evidence list -- never a fabricated fact."""
    G = _build_test_graph()
    res = describe_workflow(G, "model.missing")
    assert res.status == QueryStatus.NOT_FOUND
    assert res.evidence == []
