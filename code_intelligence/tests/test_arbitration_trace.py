from types import SimpleNamespace

import pytest

from code_intelligence.agent.resolution import fuzzy_lookup
from code_intelligence.agent.resolution.arbitration import (
    ARBITRATION_CALL_FAILED,
    ARBITRATION_NO_LLM,
    ARBITRATION_NONE,
    ARBITRATION_OUT_OF_LIST,
    ARBITRATION_SELECTED,
    ArbitrationTrace,
    _llm_arbitrate,
)
from code_intelligence.agent.resolution.candidates import ArbitrationShortlist

CANDIDATES = ["sale.order", "purchase.order"]


def _answer_with(monkeypatch, content=None, error=None):
    def fake_invoke(llm, messages, rebuild_llm=None):
        if error is not None:
            raise error
        return SimpleNamespace(content=content), 0.0

    monkeypatch.setattr("core.llm.llm_client.invoke_with_rate_limit", fake_invoke)


def test_no_llm_gives_the_no_llm_status_and_no_raw_answer():
    trace = _llm_arbitrate("q", CANDIDATES, None)

    assert trace == ArbitrationTrace(None, ARBITRATION_NO_LLM, None)


def test_a_listed_answer_is_selected_and_kept_raw(monkeypatch):
    _answer_with(monkeypatch, "purchase.order")

    trace = _llm_arbitrate("q", CANDIDATES, object())

    assert trace == ArbitrationTrace("purchase.order", ARBITRATION_SELECTED, "purchase.order")


def test_none_answer_is_an_explicit_abstention(monkeypatch):
    _answer_with(monkeypatch, "NONE")

    trace = _llm_arbitrate("q", CANDIDATES, object())

    assert trace == ArbitrationTrace(None, ARBITRATION_NONE, "NONE")


def test_an_answer_outside_the_list_keeps_its_exact_raw_value(monkeypatch):
    _answer_with(monkeypatch, "`purchase.order`")

    trace = _llm_arbitrate("q", CANDIDATES, object())

    assert trace == ArbitrationTrace(None, ARBITRATION_OUT_OF_LIST, "`purchase.order`")


def test_a_failed_call_is_told_apart_from_an_abstention(monkeypatch):
    _answer_with(monkeypatch, error=RuntimeError("tunnel down"))

    trace = _llm_arbitrate("q", CANDIDATES, object())

    assert trace == ArbitrationTrace(None, ARBITRATION_CALL_FAILED, None)


def test_diagnostics_hold_the_status_and_the_truncated_raw_answer():
    shortlist = ArbitrationShortlist(CANDIDATES, None)
    trace = ArbitrationTrace(None, ARBITRATION_OUT_OF_LIST, "x" * 500)

    diagnostics = fuzzy_lookup._diagnostics(shortlist, trace=trace)

    assert diagnostics[fuzzy_lookup.ARBITRATION_OUTCOME_KEY] == ARBITRATION_OUT_OF_LIST
    assert diagnostics[fuzzy_lookup.ARBITRATION_RAW_KEY] == "x" * fuzzy_lookup.ARBITRATION_RAW_MAX_LENGTH


def test_diagnostics_have_no_raw_key_when_the_arbiter_gave_no_answer():
    shortlist = ArbitrationShortlist(CANDIDATES, None)

    diagnostics = fuzzy_lookup._diagnostics(shortlist, trace=ArbitrationTrace(None, ARBITRATION_CALL_FAILED))

    assert diagnostics == {fuzzy_lookup.ARBITRATION_OUTCOME_KEY: ARBITRATION_CALL_FAILED}


def test_diagnostics_have_no_arbitration_key_when_the_arbiter_was_not_called():
    assert fuzzy_lookup._diagnostics(ArbitrationShortlist(CANDIDATES, None)) == {}


def _patch_strict_ties(monkeypatch, trace):
    ties = [("sale.order", 90.0), ("purchase.order", 90.0)]
    monkeypatch.setattr(fuzzy_lookup, "_fuzzy_match_graph", lambda *args, **kwargs: ties)
    monkeypatch.setattr(fuzzy_lookup, "_deterministic_tiebreak", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        fuzzy_lookup, "build_arbitration_shortlist",
        lambda *args, **kwargs: ArbitrationShortlist(CANDIDATES, None),
    )
    monkeypatch.setattr(fuzzy_lookup, "_candidate_contexts", lambda *args, **kwargs: {})
    monkeypatch.setattr(fuzzy_lookup, "_llm_arbitrate", lambda *args, **kwargs: trace)


def test_strict_branch_publishes_the_outcome_and_raw_answer_when_nothing_is_chosen(monkeypatch):
    _patch_strict_ties(monkeypatch, ArbitrationTrace(None, ARBITRATION_OUT_OF_LIST, "Purchase Order"))

    concept = fuzzy_lookup.resolve_fuzzy_match("q", "q", object(), object(), "fr_FR", False)

    assert concept.is_resolved is False
    assert concept.diagnostics[fuzzy_lookup.ARBITRATION_OUTCOME_KEY] == ARBITRATION_OUT_OF_LIST
    assert concept.diagnostics[fuzzy_lookup.ARBITRATION_RAW_KEY] == "Purchase Order"


def test_strict_branch_publishes_the_outcome_of_a_chosen_model(monkeypatch):
    _patch_strict_ties(monkeypatch, ArbitrationTrace("purchase.order", ARBITRATION_SELECTED, "purchase.order"))

    concept = fuzzy_lookup.resolve_fuzzy_match("q", "q", object(), object(), "fr_FR", False)

    assert concept.is_resolved is True
    assert concept.diagnostics[fuzzy_lookup.ARBITRATION_OUTCOME_KEY] == ARBITRATION_SELECTED


def _patch_widened_only(monkeypatch, shortlist_models, arbiter):
    monkeypatch.setattr(
        fuzzy_lookup, "_fuzzy_match_graph",
        lambda *args, **kwargs: [("sale.order", 40.0)] if "threshold" in kwargs else [],
    )
    monkeypatch.setattr(
        fuzzy_lookup, "build_arbitration_shortlist",
        lambda *args, **kwargs: ArbitrationShortlist(shortlist_models, None),
    )
    monkeypatch.setattr(fuzzy_lookup, "_candidate_contexts", lambda *args, **kwargs: {})
    monkeypatch.setattr(fuzzy_lookup, "_llm_arbitrate", arbiter)


def test_widened_branch_publishes_the_outcome_and_raw_answer(monkeypatch):
    _patch_widened_only(
        monkeypatch, CANDIDATES, lambda *args, **kwargs: ArbitrationTrace(None, ARBITRATION_NONE, "NONE"),
    )

    concept = fuzzy_lookup.resolve_fuzzy_match("q", "q", object(), object(), "fr_FR", False)

    assert concept.is_resolved is False
    assert concept.diagnostics[fuzzy_lookup.ARBITRATION_OUTCOME_KEY] == ARBITRATION_NONE
    assert concept.diagnostics[fuzzy_lookup.ARBITRATION_RAW_KEY] == "NONE"


def test_widened_branch_does_not_call_the_arbiter_for_an_empty_list(monkeypatch):
    def arbiter_must_not_run(*args, **kwargs):
        raise AssertionError("the arbiter must not be called on an empty list")

    _patch_widened_only(monkeypatch, [], arbiter_must_not_run)

    concept = fuzzy_lookup.resolve_fuzzy_match("q", "q", object(), object(), "fr_FR", False)

    assert concept.is_resolved is False
    assert fuzzy_lookup.ARBITRATION_OUTCOME_KEY not in concept.diagnostics
    assert fuzzy_lookup.ARBITRATION_RAW_KEY not in concept.diagnostics


@pytest.mark.parametrize(
    "llm, expected_fragment",
    [
        (None, "no LLM was available for arbitration"),
        (object(), "LLM arbitration did not select one"),
    ],
)
def test_the_reason_says_whether_an_llm_was_available(monkeypatch, llm, expected_fragment):
    _patch_widened_only(
        monkeypatch, CANDIDATES,
        lambda *args, **kwargs: ArbitrationTrace(None, ARBITRATION_NO_LLM if llm is None else ARBITRATION_NONE),
    )

    concept = fuzzy_lookup.resolve_fuzzy_match("q", "q", object(), llm, "fr_FR", False)

    assert expected_fragment in concept.reason
