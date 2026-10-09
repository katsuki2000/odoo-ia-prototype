# -*- coding: utf-8 -*-
"""
Design decision made explicitly with the maitre de stage: H3 sits AFTER
route() (code_intelligence_agent), never before -- it never changes
route_decision. See rag/evidence_check.py's module docstring for the full
rationale (rejected alternative: H3 before route() collapses into H4, the
least-evidenced hypothesis from  section 60/61).

This file locks two distinct things:
  1. rag.evidence_check.check_evidence() itself -- the RESOLU/NON_RESOLU/
     CONFLIT decision, given the two inputs code_intelligence_agent
     supplies.
  2. rag.routing.route()'s new resolved_concept_reused flag -- the object-
     identity computation that check_evidence's CONFLIT case depends on.
"""
import dataclasses
from unittest.mock import patch

import networkx as nx
import pytest

from code_intelligence.agent.matching import ResolvedConcept
from core.evidence.evidence_check import check_evidence
from core.routing.routing import route


@pytest.fixture(autouse=True)
def _fixed_instance_graph():
    graph = nx.DiGraph()
    graph.add_node("model:custom.asset.loan", node_type="Model", name="custom.asset.loan")
    with patch("code_intelligence.graph.loader.get_code_intelligence_graph", return_value=graph):
        yield


def _unresolved(user_term="et pour cette annee ?") -> ResolvedConcept:
    return ResolvedConcept(user_term=user_term, is_resolved=False, source_step="unresolved")


def _resolved(user_term="facture", models=None) -> ResolvedConcept:
    return ResolvedConcept(
        user_term=user_term,
        resolved_models=models or ["account.move"],
        confidence=1.0,
        source_step="static_alias",
        is_resolved=True,
        reason=f"Matched static aliases: {user_term}",
    )


# ── check_evidence() ────────────────────────────────────────────────────────

def test_resolved_before_rehydration_is_resolu_regardless_of_state():
    """Highest-trust case: this branch's own resolution succeeded on its
    own -- state is irrelevant, never even consulted for the reused flag."""
    concept = _resolved()
    status = check_evidence(concept, True, {"resolved_concept_reused": True})
    assert status == "RESOLU"


def test_still_unresolved_after_rehydration_is_non_resolu():
    concept = _unresolved()
    status = check_evidence(concept, False, {"resolved_concept_reused": False})
    assert status == "NON_RESOLU"


def test_still_unresolved_after_rehydration_is_non_resolu_even_if_reused_flag_somehow_true():
    """Defensive: resolved_concept_reused=True with a concept that is
    still NOT resolved is a contradiction that should never occur in
    practice (route()'s own resolved_concept_reused is only True when the
    reused dict itself was is_resolved=True) -- but NON_RESOLU must win
    regardless, never CONFLIT, since there is genuinely nothing resolved
    to be in conflict about."""
    concept = _unresolved()
    status = check_evidence(concept, False, {"resolved_concept_reused": True})
    assert status == "NON_RESOLU"


def test_rehydrated_from_this_turns_own_route_resolution_is_resolu():
    """Rehydrated (this branch's own attempt failed), but NOT reused from
    a previous turn -- route()'s own no-LLM resolution of THIS question's
    text found it. Still the current question's own text, just resolved at
    a cheaper tier -- RESOLU, not CONFLIT."""
    concept = _resolved()  # what _rehydrate_sticky_concept would have produced
    status = check_evidence(concept, False, {"resolved_concept_reused": False})
    assert status == "RESOLU"


def test_rehydrated_and_reused_from_previous_turn_is_conflit():
    """The actual risk case: rehydrated, AND that rehydration source was
    itself only available because route() carried it over from a
    different, earlier turn -- not resolved from this question's own
    text anywhere in the pipeline."""
    concept = _resolved()
    status = check_evidence(concept, False, {"resolved_concept_reused": True})
    assert status == "CONFLIT"


def test_missing_reused_key_defaults_to_resolu_not_conflit():
    """state.get("resolved_concept_reused") on a state dict that never
    set the key (e.g. every pre-H3 test fixture, or a branch other than
    code_intelligence) must behave like False, never crash and never be
    mistaken for CONFLIT."""
    concept = _resolved()
    status = check_evidence(concept, False, {})
    assert status == "RESOLU"


# ── route()'s resolved_concept_reused flag ─────────────────────────────────

def _route_state(question: str, last_resolved_concept=None) -> dict:
    return {
        "question": question,
        "retrieved_chunks": [],
        "chat_history": [],
        "timing": {},
        "last_route": None,
        "last_resolved_concept": last_resolved_concept,
    }


def test_resolved_concept_reused_false_on_first_turn_no_last_concept():
    result = route(_route_state("Qui a acces a ce module ?"))
    assert result["resolved_concept_reused"] is False


def test_resolved_concept_reused_false_when_current_question_resolves_itself():
    """"mise a disposition" resolves via a static alias on its own (the
    exact DOC-08 term,  section 62) -- must not be flagged as
    reused even though a last_resolved_concept is offered, since this
    turn's own text is what produced the resolution."""
    last_concept = dataclasses.asdict(_resolved(user_term="autre chose", models=["hr.leave"]))
    result = route(_route_state(
        "Quel est le delai de traitement pour une demande de mise a disposition ?",
        last_resolved_concept=last_concept,
    ))
    assert result["resolved_concept_reused"] is False
    assert result["resolved_concept"]["user_term"] != "autre chose"


def test_resolved_concept_reused_true_when_current_text_has_nothing_and_last_concept_resolved():
    last_concept = dataclasses.asdict(_resolved(user_term="facture", models=["account.move"]))
    result = route(_route_state("Et pour cette annee ?", last_resolved_concept=last_concept))
    assert result["resolved_concept_reused"] is True
    assert result["resolved_concept"] == last_concept


def test_resolved_concept_reused_false_when_last_concept_itself_unresolved():
    last_concept = dataclasses.asdict(_unresolved())
    result = route(_route_state("Et pour cette annee ?", last_resolved_concept=last_concept))
    assert result["resolved_concept_reused"] is False
