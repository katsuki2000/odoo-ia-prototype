"""
tests/test_bloc_b2_pilot_wiring.py

Bloc B2 (todo/contexte.txt section 622-623) -- pilot wiring, end-to-end:
two tool wrappers (who_has_access_to/CI, get_total_sales/ORM) now call
core.evidence.evidence_collector.record_evidence() before returning their str, and
core/graph.py::query_graph() drains the accumulator into
AssistantResponse.evidence_dossier. Validates the full chain without a
real LLM/Odoo/graph run (build_graph()/app.invoke() mocked, same
convention as tests/test_graph.py's local LLM client mocking).
"""

from unittest.mock import patch, MagicMock

import pytest

from core.evidence.evidence import EvidenceSourceType, make_evidence
from core.evidence.evidence_collector import _turn_evidence_ctx, record_evidence
from core.schemas import AssistantResponse


@pytest.fixture(autouse=True)
def _reset_turn_evidence_ctx():
    _turn_evidence_ctx.set(None)
    yield
    _turn_evidence_ctx.set(None)


# ── Wrapper-level: get_total_sales (ORM) ───────────────────────────────────

def test_get_total_sales_wrapper_records_evidence():
    from core.evidence.evidence_collector import start_evidence_collection, collect_and_clear_evidence
    from erp_data.tools.sales import get_total_sales
    from erp_data._odoo_helpers import odoo_uid_ctx

    start_evidence_collection()
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 4200.5}]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_total_sales.invoke({"client": "", "periode": "", "statut": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)  # unchanged tool contract (B0 decision, still honored)
    dossier = collect_and_clear_evidence()
    assert len(dossier) == 1
    assert dossier[0].source_type == EvidenceSourceType.ORM


def test_get_total_sales_wrapper_without_active_turn_does_not_raise():
    """No start_evidence_collection() called -- the wrapper must still work
    (tool contract untouched), evidence is just dropped with a warning."""
    from erp_data.tools.sales import get_total_sales
    from erp_data._odoo_helpers import odoo_uid_ctx

    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 4200.5}]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_total_sales.invoke({"client": "", "periode": "", "statut": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)
    assert isinstance(result, str)


# ── Wrapper-level: who_has_access_to (CI) ──────────────────────────────────

def test_who_has_access_to_wrapper_records_evidence(monkeypatch):
    from core.evidence.evidence_collector import start_evidence_collection, collect_and_clear_evidence
    from code_intelligence.agent import tools as ci_agent_tools
    from code_intelligence.agent.tools.helpers import set_graph_ref
    import networkx as nx

    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    set_graph_ref(G)

    fake_evidence = [make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim="fake ACL grant",
        source="test:fixture",
        value=True,
        scope={},
    )]

    class _FakeResult:
        summary_text = "OK"
        evidence = fake_evidence

    def _fake_impl(G, model_name, permission="read", group_id=None):
        return _FakeResult()

    monkeypatch.setattr(
        "code_intelligence.rules.access_evaluator.who_has_access_to", _fake_impl
    )

    start_evidence_collection()
    result = ci_agent_tools.who_has_access_to.invoke({"model_name": "sale.order", "permission": "read"})
    assert result == "OK"  # unchanged tool contract
    dossier = collect_and_clear_evidence()
    assert dossier == fake_evidence


# ── query_graph() wiring: drains the accumulator into evidence_dossier ────

def test_query_graph_populates_evidence_dossier_from_tools_run_during_invoke():
    """build_graph()/app.invoke() mocked: simulates a turn where a wired
    tool ran (calling record_evidence directly, standing in for the real
    ReAct loop actually invoking get_total_sales/who_has_access_to) and
    checks query_graph() drains it into the returned AssistantResponse."""
    from core.graph import graph as core_graph  # noqa: F401 -- imports the submodule (core.graph.graph), NOT the core.graph package: build_graph()/query_graph() are defined here and query_graph() resolves build_graph() via THIS module's globals, so patch.object must target this object, not the package re-export (see todo/contexte.txt, monkeypatch cross-namespace fix).

    fake_evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim="simulated tool run during this turn",
        source="test:fixture",
        value=42,
        scope={},
    )

    def _fake_invoke(initial_state):
        # Stands in for a tool wrapper having called record_evidence()
        # somewhere inside the real graph's node execution.
        record_evidence(fake_evidence)
        return {
            "timing": {},
            "response": AssistantResponse(answer="reponse simulee", sources=[], confidence=1.0),
        }

    fake_app = MagicMock()
    fake_app.invoke.side_effect = _fake_invoke

    with patch.object(core_graph, "build_graph", return_value=fake_app):
        response = core_graph.query_graph(question="question de test")

    assert len(response.evidence_dossier) == 1
    assert response.evidence_dossier[0].claim == "simulated tool run during this turn"


def test_query_graph_starts_fresh_each_call_no_leak_across_turns():
    """A second call must not see the first turn's evidence, proving the
    accumulator is reset (not merely appended-to) at the start of each
    query_graph() invocation."""
    from core.graph import graph as core_graph

    def _make_fake_invoke(claim: str):
        def _fake_invoke(initial_state):
            record_evidence(make_evidence(
                source_type=EvidenceSourceType.ORM, claim=claim,
                source="test:fixture", value=1, scope={},
            ))
            return {
                "timing": {},
                "response": AssistantResponse(answer="reponse simulee", sources=[], confidence=1.0),
            }
        return _fake_invoke

    fake_app_1 = MagicMock()
    fake_app_1.invoke.side_effect = _make_fake_invoke("turn 1 fact")
    with patch.object(core_graph, "build_graph", return_value=fake_app_1):
        response_1 = core_graph.query_graph(question="premiere question")
    assert [e.claim for e in response_1.evidence_dossier] == ["turn 1 fact"]

    fake_app_2 = MagicMock()
    fake_app_2.invoke.side_effect = _make_fake_invoke("turn 2 fact")
    with patch.object(core_graph, "build_graph", return_value=fake_app_2):
        response_2 = core_graph.query_graph(question="deuxieme question")
    assert [e.claim for e in response_2.evidence_dossier] == ["turn 2 fact"]


def test_query_graph_exception_path_still_resets_accumulator():
    """If app.invoke() raises, the except branch returns a fresh
    AssistantResponse -- but the finally-block safety net must still drain
    the partial accumulator so it can't leak into the next call on this
    thread/context."""
    from core.graph import graph as core_graph

    def _fake_invoke(initial_state):
        record_evidence(make_evidence(
            source_type=EvidenceSourceType.ORM, claim="partial fact before crash",
            source="test:fixture", value=1, scope={},
        ))
        raise RuntimeError("simulated pipeline failure")

    fake_app = MagicMock()
    fake_app.invoke.side_effect = _fake_invoke
    with patch.object(core_graph, "build_graph", return_value=fake_app):
        response = core_graph.query_graph(question="question qui echoue")

    assert response.evidence_dossier == []  # default, error path never touches it
    assert _turn_evidence_ctx.get() is None  # safety net drained the partial bucket
