import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from core.evidence.evidence import EvidenceSourceType, make_evidence
from core.evidence.evidence_collector import (
    collect_and_clear_evidence,
    record_evidence,
    start_evidence_collection,
)
from core.graph import verify_node
from core.graph.graph import build_graph
from core.graph.graph_nodes import answered_by_documents
from core.state import RAGState
from core.schemas import AssistantResponse
from core.verification.claims import VerifierMode
from erp_data import orm_agent_node
from tests.t2_graph_factory import build_graph as build_code_graph

DOC_QUESTION = "Selon le wiki, quelle est la procedure ?"
PLAIN_QUESTION = "Qui peut approuver une commande ?"
UNKNOWN_GROUP_ANSWER = "Le groupe purchase.group_purchase_director peut approuver."


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    monkeypatch.setattr("code_intelligence.graph.loader.get_code_intelligence_graph", lambda **_: build_code_graph())
    monkeypatch.setattr(verify_node, "default_base_model_methods", lambda: frozenset({"write"}))
    start_evidence_collection()
    yield
    collect_and_clear_evidence()


@pytest.fixture
def run_node(monkeypatch):
    def run(mode, answer, **state_overrides):
        monkeypatch.setattr(verify_node, "VERIFIER_MODE", mode)
        state = {
            "question": PLAIN_QUESTION,
            "response": AssistantResponse(answer=answer, sources=[], confidence=1.0),
            "raw_tool_output": "",
            "retrieved_chunks": [],
        }
        state.update(state_overrides)
        return state, verify_node.verify_answer(state)

    return run


def _unsupported_texts(state):
    return [claim.text for claim in state["response"].verification.unsupported]


def test_off_mode_leaves_the_response_untouched(run_node):
    state, result = run_node(VerifierMode.OFF, UNKNOWN_GROUP_ANSWER)
    assert result == {}
    assert state["response"].verification is None


@pytest.mark.parametrize("response", [None, AssistantResponse(answer="", sources=[], confidence=0.0)])
def test_missing_or_empty_response_is_skipped(run_node, response):
    _, result = run_node(VerifierMode.REPORT, "unused", response=response)
    assert result == {}


def test_report_mode_attaches_the_report_and_keeps_the_answer(run_node):
    state, result = run_node(VerifierMode.REPORT, UNKNOWN_GROUP_ANSWER)
    response = state["response"]
    assert result["response"] is response
    assert response.answer == UNKNOWN_GROUP_ANSWER
    assert response.verification.claims_total == 1
    assert [(item.text, item.reason) for item in response.verification.unsupported] == [
        ("purchase.group_purchase_director", "unknown_group"),
    ]


def test_enforce_mode_writes_the_verified_answer(run_node):
    answer = "Le seuil est de 10 000. " + UNKNOWN_GROUP_ANSWER
    state, _ = run_node(VerifierMode.ENFORCE, answer, raw_tool_output="if amount > 10000:")
    response = state["response"]
    assert "Le seuil est de 10 000." in response.answer
    assert "group_purchase_director peut approuver" not in response.answer
    assert response.verification.unsupported_claims == 1


def test_number_is_supported_by_tool_observations(run_node):
    state, _ = run_node(VerifierMode.REPORT, "Total : 7,5 unites.", raw_tool_output="Il y a 7.5 unites.")
    assert state["response"].verification.unsupported_claims == 0
    state, _ = run_node(VerifierMode.REPORT, "Total : 7,5 unites.")
    assert _unsupported_texts(state) == ["7,5"]


def test_number_is_supported_by_the_question(run_node):
    state, _ = run_node(
        VerifierMode.REPORT, "Oui, le seuil de 15 000 est atteint.",
        question="Le seuil de 15 000 est-il atteint ?",
    )
    assert state["response"].verification.unsupported_claims == 0


def test_numeric_turn_evidence_supports_a_number(run_node):
    record_evidence(make_evidence(
        EvidenceSourceType.ORM, claim="Total quantity in stock", source="stock.quant", value=12500.0,
    ))
    state, _ = run_node(VerifierMode.REPORT, "Il y a 12 500 unites.")
    assert state["response"].verification.unsupported_claims == 0


def test_documentary_branch_is_grounded_in_the_retrieved_chunks_only(run_node):
    state, _ = run_node(
        VerifierMode.REPORT, "Le seuil est de 5 000 euros, puis 9 999.",
        question=DOC_QUESTION,
        route="documentaire",
        ci_evidence_sufficiency={"status": "insufficient"},
        retrieved_chunks=[{"document": "Le seuil est de 5000 euros."}],
        raw_tool_output="limite 9999",
    )
    assert _unsupported_texts(state) == ["9 999"]


def test_retrieved_chunks_are_not_evidence_when_another_branch_answered(run_node):
    state, _ = run_node(
        VerifierMode.REPORT, "Le seuil est de 5 000.",
        retrieved_chunks=[{"document": "Le seuil est de 5000 euros."}],
    )
    assert _unsupported_texts(state) == ["5 000"]


def test_answer_is_not_reformatted_before_claims_are_extracted(run_node):
    answer = '<ol start="7"><li>un</li></ol>'
    state, _ = run_node(VerifierMode.REPORT, answer)
    assert state["response"].answer == answer


def test_unavailable_graph_degrades_to_evidence_only(run_node, monkeypatch):
    def broken_loader(**_):
        raise RuntimeError("graph unavailable")

    monkeypatch.setattr("code_intelligence.graph.loader.get_code_intelligence_graph", broken_loader)
    state, _ = run_node(
        VerifierMode.REPORT, UNKNOWN_GROUP_ANSWER + " Le groupe account.group_account_manager aussi.",
        raw_tool_output="(groupes: account.group_account_manager)",
    )
    assert [(item.text, item.reason) for item in state["response"].verification.unsupported] == [
        ("purchase.group_purchase_director", "not_in_evidence"),
    ]


def test_verifier_failure_never_breaks_the_answer(run_node, monkeypatch, caplog):
    def failing(*_args, **_kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(verify_node, "verify_answer_claims", failing)
    state, result = run_node(VerifierMode.ENFORCE, UNKNOWN_GROUP_ANSWER)
    assert result == {}
    assert state["response"].answer == UNKNOWN_GROUP_ANSWER
    assert state["response"].verification is None
    assert "Answer verifier failed" in caplog.text


@pytest.mark.parametrize("state, expected", [
    ({"question": DOC_QUESTION, "route": "documentaire"}, True),
    ({"question": DOC_QUESTION, "source_mode": "documentation"}, True),
    ({"question": DOC_QUESTION}, False),
    ({"question": PLAIN_QUESTION, "route": "code_intelligence"}, False),
])
def test_answered_by_documents(state, expected):
    assert answered_by_documents(state) is expected


def test_undeclared_state_keys_are_dropped_and_raw_tool_output_is_declared():
    def node(_state):
        return {"raw_tool_output": "observations", "unknown_key": "lost"}

    workflow = StateGraph(RAGState)
    workflow.add_node("node", node)
    workflow.add_edge(START, "node")
    workflow.add_edge("node", END)
    final_state = workflow.compile().invoke({"question": "q"})
    assert final_state["raw_tool_output"] == "observations"
    assert "unknown_key" not in final_state


def test_orm_loop_returns_the_tool_observations(monkeypatch):
    class SilentTraceLogger:
        def log_hop(self, **_kwargs):
            pass

        def log_summary(self, **_kwargs):
            pass

    class FakeLlm:
        def bind_tools(self, _tools):
            return self

    tool_calls = [
        {"name": "get_stock", "args": {"produit": "a"}, "id": "call_1"},
        {"name": "get_stock", "args": {"produit": "b"}, "id": "call_2"},
    ]
    observations = iter(["Il y a 7.0 unites de a.", "Il y a 3.0 unites de b."])
    turns = {"n": 0}

    def fake_invoke(*_args, **_kwargs):
        turns["n"] += 1
        if turns["n"] == 1:
            return AIMessage(content="", tool_calls=tool_calls), 0.0
        return AIMessage(content="Stock a=7, b=3."), 0.0

    monkeypatch.setattr(orm_agent_node, "ReasoningTraceLogger", SilentTraceLogger)
    monkeypatch.setattr(orm_agent_node, "is_out_of_scope", lambda _question: False)
    monkeypatch.setattr(orm_agent_node, "resolve_orm_tools", lambda _skills: [])
    monkeypatch.setattr(orm_agent_node, "_build_llm", lambda **_kwargs: FakeLlm())
    monkeypatch.setattr(orm_agent_node, "_invoke_with_rate_limit", fake_invoke)
    monkeypatch.setattr(
        orm_agent_node, "execute_tool_call",
        lambda tool_call, _tools: (tool_call["name"], tool_call["args"], next(observations)),
    )
    result = orm_agent_node.orm_agent_loop({"question": "Combien en stock ?"})
    assert result["raw_tool_output"] == "Il y a 7.0 unites de a.\n\nIl y a 3.0 unites de b."
    assert result["response"].answer == "Stock a=7, b=3."
    assert turns["n"] == 2


def _incoming(graph_view, target):
    return {edge.source for edge in graph_view.edges if edge.target == target}


def test_verify_answer_is_the_only_branch_entry_into_format_output():
    graph_view = build_graph().get_graph()
    assert {edge.target for edge in graph_view.edges if edge.source == "verify_answer"} == {"format_output"}
    assert _incoming(graph_view, "format_output") == {"out_of_scope_gate", "verify_answer"}
    assert _incoming(graph_view, "verify_answer") == {"code_intelligence_agent", "generate", "orm_agent_loop"}
