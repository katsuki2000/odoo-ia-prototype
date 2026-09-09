"""
code_intelligence/tests/test_bloc_b1_evidence_trace_full_inheritance.py

B1 replication of the B0 pilot (todo/contexte.txt sections 426-446):
validates that trace_full_inheritance() produces structured Evidence at
the source -- one per direct EXTENDS (_inherit) parent, one per direct
DELEGATES_TO (_inherits) parent, or a single explicit "no inheritance"
fact when neither is found. Fourth of the 5 composite CI tools in the
retained order (composites -> analyse -> aux -> ORM, section 440);
button_execution_path (3/24) closed in section 446.
"""

import networkx as nx

from code_intelligence.deterministic.inheritance_chain import trace_full_inheritance
from code_intelligence.deterministic.common import QueryStatus
from core.evidence import Evidence, EvidenceSourceType


def _build_test_graph() -> nx.DiGraph:
    """Synthetic graph, hand-built (not via the real corpus-load path, kept
    for cycle-safety by test_bloc8_j27_inheritance_cycle_regression.py
    already), covering all 3 branches in one small graph:
      - 'child.mixed' extends 'parent.ext1' and 'parent.ext2' (2 EXTENDS)
        AND delegates to 'parent.deleg' via fk 'deleg_id' (1 DELEGATES_TO)
        -- exercises both fact kinds together on the same model.
      - 'child.leaf' has no EXTENDS/DELEGATES_TO edges at all -- exercises
        the explicit "no inheritance" fact (EMPTY status).
      - 'model.missing' is never added as a node -- exercises the
        NOT_FOUND branch (empty evidence, no fabricated fact).
    """
    G = nx.DiGraph()

    for m in ("child.mixed", "parent.ext1", "parent.ext2", "parent.deleg", "child.leaf"):
        G.add_node(f"model:{m}", node_type="Model")

    G.add_edge("model:child.mixed", "model:parent.ext1", edge_type="EXTENDS")
    G.add_edge("model:child.mixed", "model:parent.ext2", edge_type="EXTENDS")
    G.add_edge("model:child.mixed", "model:parent.deleg", edge_type="DELEGATES_TO", fk_field="deleg_id")

    return G


def test_evidence_count_mixed_extends_and_delegates():
    """2 EXTENDS + 1 DELEGATES_TO = 3 Evidence, no 'no inheritance' fact."""
    G = _build_test_graph()
    res = trace_full_inheritance(G, "child.mixed")
    assert res.status == QueryStatus.FOUND
    assert len(res.evidence) == 3
    assert all(isinstance(e, Evidence) for e in res.evidence)


def test_evidence_source_type_and_confidence():
    """CI evidence is CODE-sourced and marked HIGH confidence, same
    vocabulary as the B0/B1 precedents."""
    G = _build_test_graph()
    res = trace_full_inheritance(G, "child.mixed")
    for e in res.evidence:
        assert e.source_type == EvidenceSourceType.CODE
        assert e.confidence == "HIGH"


def test_evidence_extension_claim_and_value():
    """One Evidence per direct EXTENDS parent, sourced by the
    'extends:{model}:{parent}' key, value = the parent model name."""
    G = _build_test_graph()
    res = trace_full_inheritance(G, "child.mixed")
    e = next(ev for ev in res.evidence if ev.source == "extends:child.mixed:parent.ext1")
    assert e.value == "parent.ext1"
    assert "extends 'parent.ext1' via _inherit" in e.claim


def test_evidence_second_extension_parent_also_present():
    """Both EXTENDS parents get their own Evidence, not just the first."""
    G = _build_test_graph()
    res = trace_full_inheritance(G, "child.mixed")
    e = next(ev for ev in res.evidence if ev.source == "extends:child.mixed:parent.ext2")
    assert e.value == "parent.ext2"


def test_evidence_delegation_claim_and_value_is_fk_field():
    """DELEGATES_TO Evidence value is the fk_field (not the parent model
    name), sourced by the 'delegates_to:{model}:{parent}' key."""
    G = _build_test_graph()
    res = trace_full_inheritance(G, "child.mixed")
    e = next(ev for ev in res.evidence if ev.source == "delegates_to:child.mixed:parent.deleg")
    assert e.value == "deleg_id"
    assert "delegates to 'parent.deleg' via _inherits" in e.claim
    assert "deleg_id" in e.claim


def test_evidence_no_inheritance_produces_explicit_fact():
    """A model with neither EXTENDS nor DELEGATES_TO edges (EMPTY status)
    still asserts one explicit negative fact -- never silently empty."""
    G = _build_test_graph()
    res = trace_full_inheritance(G, "child.leaf")
    assert res.status == QueryStatus.EMPTY
    assert len(res.evidence) == 1
    e = res.evidence[0]
    assert e.source == "inherits:child.leaf"
    assert e.value is None
    assert "does not inherit from any other model" in e.claim


def test_evidence_scope_is_always_empty():
    """No requester context for a structural inheritance fact (no
    group_id/user_groups equivalent) -- scope must stay {} on every
    Evidence, mixed model and leaf model alike."""
    G = _build_test_graph()
    for model in ("child.mixed", "child.leaf"):
        res = trace_full_inheritance(G, model)
        for e in res.evidence:
            assert e.scope == {}


def test_evidence_id_is_deterministic_across_runs():
    """Same inputs -> same evidence_id across two independent calls."""
    G = _build_test_graph()
    res1 = trace_full_inheritance(G, "child.mixed")
    res2 = trace_full_inheritance(G, "child.mixed")
    ids1 = sorted(e.evidence_id for e in res1.evidence)
    ids2 = sorted(e.evidence_id for e in res2.evidence)
    assert ids1 == ids2


def test_model_not_found_produces_no_evidence():
    """A model absent from the graph returns the existing NOT_FOUND
    summary_text and an empty evidence list -- never a fabricated fact."""
    G = _build_test_graph()
    res = trace_full_inheritance(G, "model.missing")
    assert res.status == QueryStatus.NOT_FOUND
    assert res.evidence == []
