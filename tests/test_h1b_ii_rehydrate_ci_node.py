# -*- coding: utf-8 -*-
"""
H1b-ii : unit tests for
rag.ci_helpers._rehydrate_sticky_concept -- extracted 2026-08-20 out of
code_intelligence_agent() (rag/ci_agent_node.py) specifically so this
reconstruction step is testable on its own, without mocking the graph,
LLM, or tool set that function otherwise depends on.

Distinct from tests/test_h1b_ii_sticky_concept.py (rag.routing.
_sticky_concept_or_resolve, one step earlier in the pipeline, purely
dict-to-dict): this file locks the DOWNSTREAM step -- reconstructing a
real ResolvedConcept dataclass instance from the dict route() already
decided on, so code_intelligence_agent's later concept.is_resolved /
concept.resolved_models / etc. attribute access works.
"""
import dataclasses

import pytest

from code_intelligence.business_resolver import ResolvedConcept
from code_intelligence.ci_helpers import _rehydrate_sticky_concept


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


# ── Current-turn resolution already succeeded -- state ignored entirely ───

def test_current_resolved_returns_it_unchanged_ignoring_state():
    concept = _resolved()
    state = {"resolved_concept": {"is_resolved": True, "user_term": "totally different"}}
    result = _rehydrate_sticky_concept(concept, state)
    assert result is concept


def test_current_resolved_even_with_no_state_offered():
    concept = _resolved()
    result = _rehydrate_sticky_concept(concept, {})
    assert result is concept


# ── Current failed, sticky dict resolved -- reconstructs a real dataclass ──

def test_current_failed_sticky_resolved_reconstructs_usable_dataclass():
    """The core case: the sticky dict (as route() stores it, i.e. the
    output of dataclasses.asdict() on a real ResolvedConcept) must come
    back as a real ResolvedConcept instance with working attribute
    access -- not a dict, not raising AttributeError on first use."""
    concept = _unresolved()
    original = _resolved(user_term="facture", models=["account.move", "account.move.line"])
    sticky_dict = dataclasses.asdict(original)
    state = {"resolved_concept": sticky_dict}

    result = _rehydrate_sticky_concept(concept, state)

    assert isinstance(result, ResolvedConcept)
    assert result.is_resolved is True
    assert result.user_term == "facture"
    assert result.resolved_models == ["account.move", "account.move.line"]
    assert result.source_step == "static_alias"


def test_current_failed_sticky_resolved_matches_ci_agent_node_usage_pattern():
    """Mirrors exactly how code_intelligence_agent uses the result
    downstream: concept.is_resolved as a condition, concept.resolved_models
    joined into a prompt string. Locks that these don't raise."""
    concept = _unresolved()
    sticky_dict = dataclasses.asdict(_resolved(models=["hr.leave"]))
    result = _rehydrate_sticky_concept(concept, {"resolved_concept": sticky_dict})

    assert result.is_resolved
    assert result.resolved_models
    # This is the exact usage pattern in code_intelligence_agent's
    # system_prompt-building block -- must not raise.
    _ = f"Target Models: {', '.join(result.resolved_models)}"


# ── Current failed, sticky itself unresolved -- stays the original concept ─

def test_current_failed_sticky_also_unresolved_stays_original():
    concept = _unresolved()
    sticky_dict = dataclasses.asdict(_unresolved(user_term="autre question non resolue"))
    result = _rehydrate_sticky_concept(concept, {"resolved_concept": sticky_dict})
    assert result is concept
    assert result.is_resolved is False


# ── Sticky absent or corrupted -- degrades to the original concept ────────

def test_sticky_key_absent_entirely_stays_original():
    concept = _unresolved()
    result = _rehydrate_sticky_concept(concept, {})
    assert result is concept


def test_sticky_explicit_none_stays_original():
    concept = _unresolved()
    result = _rehydrate_sticky_concept(concept, {"resolved_concept": None})
    assert result is concept


def test_sticky_wrong_type_not_a_dict_stays_original():
    concept = _unresolved()
    for foreign in ["not_a_dict", 42, ["is_resolved", True]]:
        result = _rehydrate_sticky_concept(concept, {"resolved_concept": foreign})
        assert result is concept


def test_sticky_dict_missing_is_resolved_key_stays_original():
    concept = _unresolved()
    sticky_dict = {"user_term": "facture", "resolved_models": ["account.move"]}  # no is_resolved
    result = _rehydrate_sticky_concept(concept, {"resolved_concept": sticky_dict})
    assert result is concept


def test_sticky_is_resolved_truthy_but_not_strict_true_stays_original():
    concept = _unresolved()
    for truthy_not_true in ["true", 1]:
        sticky_dict = {"is_resolved": truthy_not_true, "user_term": "facture"}
        result = _rehydrate_sticky_concept(concept, {"resolved_concept": sticky_dict})
        assert result is concept


def test_sticky_dict_malformed_fields_degrades_without_raising():
    """A sticky dict with an unexpected shape (e.g. an extra key that
    doesn't match any ResolvedConcept field -- a corrupted/foreign write
    from somewhere upstream) must never crash the whole node. Degrades to
    the original (unresolved) concept instead."""
    concept = _unresolved()
    sticky_dict = {
        "is_resolved": True,
        "user_term": "facture",
        "resolved_models": ["account.move"],
        "resolved_modules": [],
        "confidence": 1.0,
        "source_step": "static_alias",
        "reason": "x",
        "totally_unexpected_extra_field": "corruption",
    }
    result = _rehydrate_sticky_concept(concept, {"resolved_concept": sticky_dict})
    assert result is concept
    assert result.is_resolved is False


def test_sticky_dict_missing_required_field_degrades_without_raising():
    """user_term has no default in ResolvedConcept -- a sticky dict
    missing it entirely must degrade gracefully, not raise TypeError up
    through code_intelligence_agent."""
    concept = _unresolved()
    sticky_dict = {"is_resolved": True, "resolved_models": ["account.move"]}  # no user_term
    result = _rehydrate_sticky_concept(concept, {"resolved_concept": sticky_dict})
    assert result is concept
