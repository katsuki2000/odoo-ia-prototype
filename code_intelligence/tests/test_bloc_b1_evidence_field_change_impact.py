"""
code_intelligence/tests/test_bloc_b1_evidence_field_change_impact.py

B1 replication of the B0 pilot (todo/contexte.txt sections 426-442):
validates that field_change_impact() produces structured Evidence at the
source, one per upstream trigger dependency and one per downstream
computed field discovered by the multi-hop BFS. Second of the 5 composite
CI tools in the retained order (composites -> analyse -> aux -> ORM,
section 440); who_has_access_to (1/24) closed in section 442.
"""

import networkx as nx

from code_intelligence.deterministic.structure.field_impact import field_change_impact
from core.evidence import Evidence, EvidenceSourceType


def _build_test_graph() -> nx.DiGraph:
    """Synthetic graph, same spirit as test_bloc9_cross_module_computed_fields
    (justificatif_manquant/total_amount -> risk_score -> alerte_conformite)
    but built by hand rather than from the real corpus, to keep this suite
    fast and independent of ADDONS_PATH. risk_score has 3 upstream
    triggers -- two plain, one with a dotted @api.depends trigger_path --
    and 1 downstream computed field one hop away, to exercise both
    branches of _build_field_impact_evidence in a single target field."""
    G = nx.DiGraph()

    G.add_node(
        "field:hr.expense.risk_score", node_type="Field", name="risk_score",
        compute="_compute_risk_score",
    )
    G.add_node("method:hr.expense._compute_risk_score", node_type="Method")
    G.add_node("field:hr.expense.justificatif_manquant", node_type="Field", name="justificatif_manquant")
    G.add_node("field:hr.expense.total_amount", node_type="Field", name="total_amount")
    G.add_node("field:hr.expense.employee_id", node_type="Field", name="employee_id")
    G.add_node(
        "field:hr.expense.alerte_conformite", node_type="Field", name="alerte_conformite",
        compute="_compute_alerte_conformite",
    )
    G.add_node("method:hr.expense._compute_alerte_conformite", node_type="Method")

    G.add_edge("field:hr.expense.risk_score", "method:hr.expense._compute_risk_score", edge_type="COMPUTED_BY")
    G.add_edge(
        "method:hr.expense._compute_risk_score", "field:hr.expense.justificatif_manquant",
        edge_type="DEPENDS_ON",
    )
    G.add_edge(
        "method:hr.expense._compute_risk_score", "field:hr.expense.total_amount",
        edge_type="DEPENDS_ON",
    )
    G.add_edge(
        "method:hr.expense._compute_risk_score", "field:hr.expense.employee_id",
        edge_type="DEPENDS_ON", trigger_path="employee_id.department_id",
    )

    G.add_edge(
        "field:hr.expense.alerte_conformite", "method:hr.expense._compute_alerte_conformite",
        edge_type="COMPUTED_BY",
    )
    G.add_edge(
        "method:hr.expense._compute_alerte_conformite", "field:hr.expense.risk_score",
        edge_type="DEPENDS_ON",
    )

    return G


def test_evidence_count_matches_upstream_plus_downstream():
    """3 upstream triggers + 1 downstream computed field = 4 Evidence."""
    G = _build_test_graph()
    res = field_change_impact(G, "risk_score", "hr.expense")
    assert len(res.evidence) == 4
    assert all(isinstance(e, Evidence) for e in res.evidence)


def test_evidence_source_type_and_confidence():
    """CI evidence is CODE-sourced and marked HIGH confidence, same
    vocabulary as the B0/B1 precedents."""
    G = _build_test_graph()
    res = field_change_impact(G, "risk_score", "hr.expense")
    for e in res.evidence:
        assert e.source_type == EvidenceSourceType.CODE
        assert e.confidence == "HIGH"


def test_evidence_upstream_trigger_uses_dotted_path_when_present():
    """employee_id's DEPENDS_ON edge carries a dotted trigger_path
    (@api.depends('employee_id.department_id')) -- the Evidence value and
    claim must surface the full dotted path, not just the short name."""
    G = _build_test_graph()
    res = field_change_impact(G, "risk_score", "hr.expense")
    e = next(ev for ev in res.evidence if ev.source == "depends_on:hr.expense.risk_score:employee_id")
    assert e.value == "employee_id.department_id"
    assert "employee_id.department_id" in e.claim


def test_evidence_upstream_trigger_uses_short_name_without_dotted_path():
    """total_amount has no dotted trigger_path -- value/claim fall back to
    the short field name."""
    G = _build_test_graph()
    res = field_change_impact(G, "risk_score", "hr.expense")
    e = next(ev for ev in res.evidence if ev.source == "depends_on:hr.expense.risk_score:total_amount")
    assert e.value == "total_amount"


def test_evidence_downstream_computed_field():
    """alerte_conformite is one BFS hop downstream of risk_score -- must
    produce its own Evidence, sourced by the full field node id."""
    G = _build_test_graph()
    res = field_change_impact(G, "risk_score", "hr.expense")
    e = next(ev for ev in res.evidence if ev.source == "field:hr.expense.alerte_conformite")
    assert e.value == "alerte_conformite"
    assert "recomputation of 'alerte_conformite'" in e.claim


def test_evidence_scope_is_always_empty():
    """Unlike who_has_access_to's group_id, there is no requester-specific
    context for a structural dependency fact -- scope must stay {}."""
    G = _build_test_graph()
    res = field_change_impact(G, "risk_score", "hr.expense")
    for e in res.evidence:
        assert e.scope == {}


def test_evidence_id_is_deterministic_across_runs():
    """Same inputs -> same evidence_id across two independent calls."""
    G = _build_test_graph()
    res1 = field_change_impact(G, "risk_score", "hr.expense")
    res2 = field_change_impact(G, "risk_score", "hr.expense")
    ids1 = sorted(e.evidence_id for e in res1.evidence)
    ids2 = sorted(e.evidence_id for e in res2.evidence)
    assert ids1 == ids2


def test_field_not_found_produces_no_evidence():
    """A field absent from the graph returns the existing NOT_FOUND
    summary_text and an empty evidence list -- never a fabricated fact."""
    G = _build_test_graph()
    res = field_change_impact(G, "does_not_exist", "hr.expense")
    assert res.evidence == []
