# -*- coding: utf-8 -*-
"""
H1b-ii (todo/contexte.txt section 64/70, todo/plan.md): unit tests for
rag.routing._sticky_concept_or_resolve -- mirrors test_h1c_sticky_routing.py's
structure and intent one level down (concept resolution instead of branch
routing).

_sticky_concept_or_resolve's contract, restated from its own docstring:
  - A current-turn resolution that already succeeded (is_resolved truthy)
    always wins untouched -- never even looks at `prev`.
  - Only reused when the previous concept is itself marked resolved with
    `is True` specifically (not merely truthy) -- rules.md Regle 4/5
    discipline: a stored is_resolved=False, a missing key, or a
    corrupted/foreign value must never be echoed back as a resolution.
  - Operates strictly on the dict form (post-_asdict), never reconstructs
    or consumes a ResolvedConcept dataclass instance itself -- see the
    dedicated test below locking that dataclasses.asdict() is never
    called from inside this function (calling asdict() on a dict instead
    of a dataclass instance raises TypeError; this was the trap route()'s
    own comment warns about for call ordering).
"""
import dataclasses

import pytest

from rag.routing import _sticky_concept_or_resolve


def _state(last_resolved_concept=None) -> dict:
    return {"last_resolved_concept": last_resolved_concept}


# ── Case 1: current-turn resolution already succeeded -- prev ignored ─────

def test_current_resolved_returns_it_unchanged_ignoring_prev():
    current = {"is_resolved": True, "user_term": "facture", "resolved_models": ["account.move"]}
    prev = {"is_resolved": True, "user_term": "totally different", "resolved_models": ["hr.leave"]}
    result = _sticky_concept_or_resolve(_state(prev), current)
    assert result is current


def test_current_resolved_truthy_but_not_strict_true_still_wins():
    """Asymmetry with the prev-side check below, deliberately locked: the
    CURRENT concept's own success check (`if resolved_concept_dict.get(
    "is_resolved")`) is a plain truthy check, not `is True` -- unlike the
    strict `is True` gate applied to `prev`. A current dict with a
    non-bool truthy is_resolved (e.g. legacy data, 1 instead of True)
    still short-circuits and returns unchanged."""
    current = {"is_resolved": 1, "user_term": "x"}
    prev = {"is_resolved": True, "user_term": "y"}
    result = _sticky_concept_or_resolve(_state(prev), current)
    assert result is current


def test_current_resolved_even_when_no_prev_offered():
    current = {"is_resolved": True, "user_term": "facture"}
    result = _sticky_concept_or_resolve(_state(None), current)
    assert result is current


# ── Case 2: current-turn resolution failed, prev resolved -- reuse prev ───

def test_current_failed_prev_resolved_reuses_prev():
    current = {"is_resolved": False, "user_term": "et pour cette annee ?"}
    prev = {"is_resolved": True, "user_term": "facture", "resolved_models": ["account.move"]}
    result = _sticky_concept_or_resolve(_state(prev), current)
    assert result is prev


# ── Case 3: current-turn failed, prev ALSO failed -- stays False ──────────

def test_current_failed_prev_also_failed_stays_false():
    current = {"is_resolved": False, "user_term": "et pour cette annee ?"}
    prev = {"is_resolved": False, "user_term": "quelque chose de non resolu"}
    result = _sticky_concept_or_resolve(_state(prev), current)
    assert result is current
    assert result["is_resolved"] is False


# ── Case 4: prev absent or corrupted -- stays False, never echoed back ────

def test_prev_absent_key_entirely_stays_false():
    """state dict never set last_resolved_concept at all (e.g. every
    pre-H1b-ii test fixture, or a session's first turn) -- must behave
    identically to an explicit None, not raise."""
    current = {"is_resolved": False, "user_term": "x"}
    result = _sticky_concept_or_resolve({}, current)
    assert result is current


def test_prev_explicit_none_stays_false():
    current = {"is_resolved": False, "user_term": "x"}
    result = _sticky_concept_or_resolve(_state(None), current)
    assert result is current


def test_prev_wrong_type_not_a_dict_stays_false():
    """A corrupted/foreign value stored upstream (e.g. a stray string, or
    a ResolvedConcept dataclass instance passed by mistake instead of its
    dict form) must never be echoed back -- isinstance gate rejects it
    before the is_resolved check is even attempted."""
    current = {"is_resolved": False, "user_term": "x"}
    for foreign in ["not_a_dict", 42, ["is_resolved", True], object()]:
        result = _sticky_concept_or_resolve(_state(foreign), current)
        assert result is current


def test_prev_dict_missing_is_resolved_key_stays_false():
    """A corrupted dict that lost its is_resolved key entirely (e.g. a
    partial write, or a schema drift) must not be treated as resolved --
    prev.get("is_resolved") is None, and None is not True."""
    current = {"is_resolved": False, "user_term": "x"}
    prev = {"user_term": "facture", "resolved_models": ["account.move"]}  # no is_resolved key
    result = _sticky_concept_or_resolve(_state(prev), current)
    assert result is current


def test_prev_is_resolved_truthy_but_not_strict_true_stays_false():
    """Unlike the CURRENT-side check (plain truthy, see test above), the
    PREV-side check is `is True` specifically -- rules.md Regle 4/5
    discipline, called out explicitly in the function's own docstring.
    A merely-truthy prev (e.g. the string "true", or 1) must NOT be
    reused."""
    current = {"is_resolved": False, "user_term": "x"}
    for truthy_not_true in ["true", 1, "yes"]:
        prev = {"is_resolved": truthy_not_true, "user_term": "facture"}
        result = _sticky_concept_or_resolve(_state(prev), current)
        assert result is current


# ── Never calls dataclasses.asdict() -- the trap route() warns about ──────

def test_never_calls_dataclasses_asdict(monkeypatch):
    """
    route()'s own comment is explicit about why this function MUST run
    strictly after dataclasses.asdict(resolved_concept) has already
    turned the current concept into a plain dict, and MUST never touch
    a dataclass instance itself: calling dataclasses.asdict() on a dict
    (as opposed to a dataclass instance) raises TypeError. Both
    `resolved_concept_dict` and `prev` are always plain dicts by the time
    they reach this function -- if a future edit mistakenly reintroduced
    a call to asdict() on either of them (e.g. while refactoring), this
    test fails loudly instead of only surfacing as a live TypeError deep
    in route()'s H1b-ii branch.
    """
    def _boom(*args, **kwargs):
        raise AssertionError(
            "_sticky_concept_or_resolve must never call dataclasses.asdict()"
        )
    monkeypatch.setattr(dataclasses, "asdict", _boom)

    # Exercise every branch above, back to back -- if any of them touched
    # dataclasses.asdict, _boom fires and the test fails.
    _sticky_concept_or_resolve(_state(None), {"is_resolved": True, "user_term": "a"})
    _sticky_concept_or_resolve(
        _state({"is_resolved": True, "user_term": "b"}),
        {"is_resolved": False, "user_term": "c"},
    )
    _sticky_concept_or_resolve(
        _state({"is_resolved": False, "user_term": "d"}),
        {"is_resolved": False, "user_term": "e"},
    )
    _sticky_concept_or_resolve(
        _state({"user_term": "missing_key"}),
        {"is_resolved": False, "user_term": "f"},
    )
    _sticky_concept_or_resolve(
        _state("not_a_dict"),
        {"is_resolved": False, "user_term": "g"},
    )
