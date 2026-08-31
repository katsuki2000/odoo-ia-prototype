# -*- coding: utf-8 -*-
"""
Tests for the out_of_scope_gate LangGraph node (core/graph.py) --
todo/contexte.txt sections 360-361.

generate()'s own _is_out_of_scope() fast-fail (document_rag/generate_node.py)
only runs after retrieve()/route() have already executed for the
DOCUMENTAIRE branch -- every out-of-scope question paid for a retrieval
call it never used. out_of_scope_gate() intercepts these questions BEFORE
retrieve() runs, same pattern and same node shape as smalltalk_gate()
(tests/test_smalltalk_gate.py).

Covers:
  - out_of_scope_gate(): must short-circuit with a complete AssistantResponse
    for any question matching OUT_OF_SCOPE_TERMS, must be a no-op (empty
    dict) for any in-scope question, must never mutate `question`.
  - out_of_scope_decision(): the node must route to "format_output" when
    the gate produced a response, "retrieve" otherwise.
"""
import pytest

from core.graph import out_of_scope_gate, out_of_scope_decision
from core.routing import OUT_OF_SCOPE_ANSWER
from core.schemas import AssistantResponse


# ── out_of_scope_gate: positive cases (short-circuits) ─────────────────────

@pytest.mark.parametrize("question", [
    "Raconte-moi une blague sur les ERP.",
    "Donne-moi une recette de gâteau.",
    "Qui a gagné la coupe du monde ?",
    "Écris-moi un poème.",
    "Est-ce que la lune est habitée ?",
])
def test_out_of_scope_gate_short_circuits_for_out_of_scope_question(question):
    state = {"question": question}
    result = out_of_scope_gate(state)

    assert "response" in result
    assert isinstance(result["response"], AssistantResponse)
    assert result["response"].answer == OUT_OF_SCOPE_ANSWER
    assert result["response"].sources == []
    assert result["response"].confidence == 0.0
    assert result["retrieved_chunks"] == []
    assert result["investigation_plan"] is None
    assert result["route"] == "out_of_scope"


# ── out_of_scope_gate: negative cases (no-op) ───────────────────────────────

@pytest.mark.parametrize("question", [
    "Comment créer une facture ?",
    "Qui a accès à ce module ?",
    "Combien de tickets sont en cours ?",
    "",
    "   ",
])
def test_out_of_scope_gate_is_noop_for_in_scope_question(question):
    """The gate must return an EMPTY dict for an in-scope question --
    LangGraph merges partial-update dicts, so an empty dict here means
    every existing state key (question included) passes through to
    retrieve()/route() completely untouched."""
    state = {"question": question}
    assert out_of_scope_gate(state) == {}


def test_out_of_scope_gate_never_mutates_the_original_question():
    state = {"question": "Raconte-moi une blague."}
    result = out_of_scope_gate(state)
    assert "question" not in result


# ── out_of_scope_decision (conditional edge) ────────────────────────────────

def test_out_of_scope_decision_routes_to_format_output_when_response_set():
    state = {"response": AssistantResponse(answer="x", sources=[], confidence=0.0)}
    assert out_of_scope_decision(state) == "format_output"


def test_out_of_scope_decision_routes_to_retrieve_when_no_response():
    state = {"response": None}
    assert out_of_scope_decision(state) == "retrieve"


def test_out_of_scope_decision_routes_to_retrieve_when_response_key_absent():
    assert out_of_scope_decision({}) == "retrieve"
