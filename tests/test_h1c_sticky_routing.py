# -*- coding: utf-8 -*-
"""
H1c : route() previously
decided purely from the current question's own text -- an elliptical
follow-up with no keyword signal of its own (e.g. "Et pour Lyon ?") always
fell to the hardcoded DOCUMENTAIRE default, even immediately after a
donnees_erp or code_intelligence turn in the same session. Confirmed as a
distinct, still-open gap by test_route_accent_fold.py's own
test_unrelated_followup_with_no_keyword_at_all_is_still_unresolved (accent
folding closed a DIFFERENT bug, not this one).

Design decided with the maître de stage: sticky-routing, not
context-informed reclassification -- when the current question has no
keyword signal, reuse the PREVIOUS turn's route (state["last_route"],
supplied by the caller from session_store) instead of guessing
DOCUMENTAIRE. Implemented as _sticky_route_or_default() in rag/graph.py,
wired into route()'s two pre-existing no-signal fallback branches only.

This file locks:
  1. Sticky-routing actually fires in both no-signal fallback branches.
  2. It stays inert on the first turn of a session (last_route=None) --
     the overwhelming majority of every existing test/benchmark question,
     none of which pass last_route, so no existing routing test can
     regress by construction.
  3. It never overrides a real keyword match -- a question that matches
     any of the seven keyword lists routes exactly the same regardless of
     what last_route says, contrary or not.
  4. An invalid/foreign last_route value is never echoed back as a route.
"""
import pytest
from core.graph import route, _sticky_route_or_default, _VALID_ROUTES
from core.schemas import QueryRoute


def _route_question(question: str, last_route=None, chunks=None) -> str:
    """Same helper as test_route_accent_fold.py's _route_question, extended
    with the two new inputs this fix introduces."""
    state = {
        "question": question,
        "retrieved_chunks": chunks if chunks is not None else [],
        "chat_history": [],
        "timing": {},
        "last_route": last_route,
    }
    return route(state)["route"]


# ── _sticky_route_or_default unit behavior ─────────────────────────────────

def test_valid_routes_set_matches_queryroute_enum():
    assert _VALID_ROUTES == {r.value for r in QueryRoute}


@pytest.mark.parametrize("last_route", [r.value for r in QueryRoute])
def test_sticky_helper_returns_last_route_when_valid(last_route):
    state = {"last_route": last_route}
    assert _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value) == last_route


def test_sticky_helper_returns_default_when_last_route_is_none():
    state = {"last_route": None}
    assert _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value) == QueryRoute.DOCUMENTAIRE.value


def test_sticky_helper_returns_default_when_last_route_key_absent():
    """state.get("last_route") on a state dict that never set the key at
    all (e.g. every pre-H1c test fixture) must behave identically to an
    explicit None -- not raise, not silently pick something else."""
    state = {}
    assert _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value) == QueryRoute.DOCUMENTAIRE.value


def test_sticky_helper_rejects_foreign_last_route_value():
    """A corrupted or foreign string stored anywhere upstream must never
    be echoed back as a route decision -- falls back to `default`."""
    state = {"last_route": "not_a_real_route"}
    assert _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value) == QueryRoute.DOCUMENTAIRE.value


# ── End-to-end through route(): the two no-signal fallback branches ───────

def test_elliptical_followup_no_chunks_sticks_to_last_route():
    """The exact case test_route_accent_fold.py left open: "Et pour Lyon
    ?" has no keyword in any of the seven lists. With no chunks retrieved
    (the "elif not chunks" branch) and a last_route from a previous
    donnees_erp turn, the question should now stick to donnees_erp
    instead of defaulting to documentaire."""
    result = _route_question("Et pour Lyon ?", last_route="donnees_erp", chunks=[])
    assert result == "donnees_erp"


def test_elliptical_followup_no_chunks_still_defaults_on_first_turn():
    """Same elliptical question, but no last_route (first turn of a
    session) -- must be byte-for-byte the same behavior as before this
    fix: defaults to documentaire. This is the regression guard for the
    overwhelming majority of real traffic (every session's first turn)."""
    assert _route_question("Et pour Lyon ?", last_route=None, chunks=[]) == "documentaire"


def test_elliptical_followup_sticks_to_code_intelligence():
    """Sticky-routing must work for every branch, not just donnees_erp --
    a follow-up after a code_intelligence turn should stick there too."""
    result = _route_question("Et pour ce cas ?", last_route="code_intelligence", chunks=[])
    assert result == "code_intelligence"


def test_erp_ratio_fallback_branch_also_sticks():
    """The second no-signal fallback (chunks retrieved, but neither a high
    ERP ratio nor a DATA_TERMS hit) must also honor sticky-routing. Chunks
    here are plain documentary chunks (no 'sale'/'ticket' type), giving
    erp_ratio=0 and no DATA_TERMS match in the question -- the same "zero
    real signal" situation as the no-chunks branch above."""
    chunks = [
        {"document": "texte de procedure", "metadata": {"type": "wiki"}},
        {"document": "autre texte", "metadata": {"type": "wiki"}},
    ]
    result = _route_question("Et sinon ?", last_route="hybride", chunks=chunks)
    assert result == "hybride"


# ── Sticky-routing must never override a real keyword match ───────────────

@pytest.mark.parametrize("question, expected_route", [
    ("Qui a accès à ce module ?", "code_intelligence"),
    ("Combien de tickets sont en cours ?", "donnees_erp"),
    ("Quelle est la procédure de validation ?", "documentaire"),
])
def test_keyword_match_wins_over_contrary_last_route(question, expected_route):
    """A question that matches a real keyword list must route exactly as
    it always did, regardless of what last_route says -- even when
    last_route explicitly points somewhere else. Sticky-routing only ever
    fires in the two zero-signal fallback branches, never here."""
    for contrary_route in _VALID_ROUTES - {expected_route}:
        assert _route_question(question, last_route=contrary_route, chunks=[]) == expected_route
