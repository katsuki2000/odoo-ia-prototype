# -*- coding: utf-8 -*-
"""
Tests for core/smalltalk.py and the smalltalk_gate LangGraph node
(core/graph.py) -- todo/contexte.txt section 294.

Covers:
  - classify_smalltalk(): pure greetings, pure thanks/farewells,
    conversational filler ("ça va ?"), the "acknowledgment" category
    (todo/contexte.txt section 301 -- "d'accord"/"entendu"/"ça marche"/
    "très bien", the 4 words empirically measured to leak past
    VECTOR_SIMILARITY_FLOOR), and the mixed cases explicitly flagged
    during review (a real business question that merely starts with a
    greeting/acknowledgment must NOT be classified as smalltalk).
  - smalltalk_gate() / smalltalk_decision(): the node must never mutate
    `question`, must produce a complete AssistantResponse (not a bare
    string), and must route onward through the pipeline ("out_of_scope_gate",
    not "format_output") for any non-smalltalk question.
"""
import pytest

from core.session.smalltalk import classify_smalltalk, SMALLTALK_RESPONSES
from core.graph.graph import smalltalk_gate, smalltalk_decision
from core.schemas import AssistantResponse


# ── classify_smalltalk: pure smalltalk (positive cases) ───────────────────

@pytest.mark.parametrize("question", [
    "Hello",
    "hello",
    "Bonjour",
    "bonjour !",
    "Bonsoir",
    "Salut",
    "Coucou",
    "Hi",
    "Hey",
    "Salut, ça va ?",
    "Comment vas-tu ?",
    "Comment allez-vous ?",
])
def test_classify_smalltalk_pure_greeting(question):
    assert classify_smalltalk(question) == "greeting"


@pytest.mark.parametrize("question", [
    "Merci",
    "merci beaucoup",
    "Merci beaucoup !",
    "Je vous remercie",
    "Au revoir",
    "A bientôt",
    "Bonne journée",
    "Bonne soirée",
    "Bye",
    "Thank you",
    "Thanks",
])
def test_classify_smalltalk_pure_thanks_farewell(question):
    assert classify_smalltalk(question) == "thanks_farewell"


# ── classify_smalltalk: NOT smalltalk (the mixed cases flagged in review) ──

@pytest.mark.parametrize("question", [
    "Bonjour, comment faire une demande de congés ?",
    "Bonjour, quel est le statut de mon ticket ?",
    "Comment créer une facture ?",
    "Merci de me dire combien de tickets sont en cours",
    "Salut, peux-tu m'expliquer la procédure d'achat ?",
    "",
    "   ",
    "Pourquoi ce bouton est grisé ?",
])
def test_classify_smalltalk_returns_none_for_business_questions(question):
    assert classify_smalltalk(question) is None


# ── classify_smalltalk: acknowledgment (section 301 calibration) ──────────

@pytest.mark.parametrize("question", [
    "d'accord",
    "D'accord",
    "D'accord !",
    "entendu",
    "Entendu.",
    "ça marche",
    "Ça marche !",
    "ca marche",
    "très bien",
    "Très bien.",
    "tres bien",
])
def test_classify_smalltalk_pure_acknowledgment(question):
    assert classify_smalltalk(question) == "acknowledgment"


@pytest.mark.parametrize("question", [
    "ok",
    "Ok",
    "compris",
    "parfait",
])
def test_classify_smalltalk_leaves_floor_handled_words_alone(question):
    """'ok'/'compris'/'parfait' are deliberately NOT in the acknowledgment
    gate -- section 301 measured them at 0/15 chunks above
    VECTOR_SIMILARITY_FLOOR, so the existing similarity floor already
    handles them correctly. Adding them here would be an unneeded second
    mechanism for a problem that doesn't exist for these words."""
    assert classify_smalltalk(question) is None


@pytest.mark.parametrize("question", [
    "D'accord, comment faire une demande de congés ?",
    "Très bien, quel est le statut de mon ticket ?",
    "Entendu, peux-tu m'expliquer la procédure d'achat ?",
    "Ça marche, merci de me dire combien de tickets sont en cours",
])
def test_classify_smalltalk_acknowledgment_returns_none_for_mixed_business_questions(question):
    """Same guard as the greeting/thanks mixed cases above: a real
    business question that happens to start with an acknowledgment word
    must NOT be swallowed by the gate before routing runs."""
    assert classify_smalltalk(question) is None


def test_classify_smalltalk_never_matches_bare_comment_prefix():
    """'comment' alone is a DOC_KEYWORDS anchor (core/routing.py) -- the
    conversational filler regex must require the FULL 'comment ça va'/
    'comment allez-vous' phrase, never just the word 'comment', or every
    documentary question starting with 'Comment ...' would be wrongly
    swallowed by the smalltalk gate before routing even runs."""
    assert classify_smalltalk("Comment est calculé ce score ?") is None
    assert classify_smalltalk("Comment est structuré ce module ?") is None


# ── smalltalk_gate node ────────────────────────────────────────────────────

def test_smalltalk_gate_returns_full_response_for_greeting():
    state = {"question": "Bonjour"}
    result = smalltalk_gate(state)

    assert "response" in result
    assert isinstance(result["response"], AssistantResponse)
    assert result["response"].answer == SMALLTALK_RESPONSES["greeting"]
    assert result["response"].sources == []
    assert result["response"].confidence == 1.0
    assert result["retrieved_chunks"] == []
    assert result["investigation_plan"] is None
    assert result["route"] == "smalltalk"


def test_smalltalk_gate_returns_full_response_for_thanks():
    state = {"question": "Merci beaucoup"}
    result = smalltalk_gate(state)

    assert result["response"].answer == SMALLTALK_RESPONSES["thanks_farewell"]


def test_smalltalk_gate_returns_full_response_for_acknowledgment():
    """Section 301: 'd'accord' must be intercepted before retrieve() so it
    never reproduces Bug C (noisy sources cited for an acquiescement that
    the similarity floor alone does not catch)."""
    state = {"question": "D'accord"}
    result = smalltalk_gate(state)

    assert result["response"].answer == SMALLTALK_RESPONSES["acknowledgment"]
    assert result["response"].sources == []
    assert result["retrieved_chunks"] == []
    assert result["route"] == "smalltalk"


def test_smalltalk_gate_is_noop_for_business_question():
    """The gate must return an EMPTY dict (no state override at all) for
    a real question -- LangGraph merges partial-update dicts, so an empty
    dict here means every existing state key (question included) passes
    through to retrieve()/route() completely untouched."""
    state = {"question": "Comment créer une facture ?"}
    result = smalltalk_gate(state)
    assert result == {}


def test_smalltalk_gate_never_mutates_the_original_question():
    """Regression guard for the review point in section 294: the gate must
    never rewrite `question`, even when it does intercept the turn --
    it must not appear as a key in its return dict at all."""
    state = {"question": "Bonjour"}
    result = smalltalk_gate(state)
    assert "question" not in result


# ── smalltalk_decision (conditional edge) ──────────────────────────────────

def test_smalltalk_decision_routes_to_format_output_when_response_set():
    state = {"response": AssistantResponse(answer="x", sources=[], confidence=1.0)}
    assert smalltalk_decision(state) == "format_output"


def test_smalltalk_decision_routes_to_out_of_scope_gate_when_no_response():
    state = {"response": None}
    assert smalltalk_decision(state) == "out_of_scope_gate"


def test_smalltalk_decision_routes_to_out_of_scope_gate_when_response_key_absent():
    assert smalltalk_decision({}) == "out_of_scope_gate"
