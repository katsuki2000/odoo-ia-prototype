"""
tests/test_bug2_backfill_scoped_output_wiring.py

Bug 2 non-regression (todo/contexte.txt section 492): every backfill/correction
guard downstream of the fail-closed scoping fix in
postprocess.py::build_final_response() must be fed through scoped_tool_output,
never through the unscoped raw_tool_output (the tool_observations join computed
BEFORE scoping). A guard silently switched to raw_tool_output would reintroduce
every falsy-model observation (resolve_technical_name / explain_decision_path /
read_source_code) that _scoped_raw_tool_output() deliberately drops.

raw_tool_output itself is legitimately used earlier for the out-of-scope /
dynamic-uncertainty checks and, deliberately, as the ground truth passed to
verify_citations() -- a citation-verification concern, not a content-backfill
channel, and explicitly excluded here.

Section 1029: _apply_backfill_chain is now a table of (guard, args, kwargs), so
the wiring is checked by behavior instead of scanning call syntax in the source:
each guard is replaced by a recorder and must receive the scoped output.
"""

import inspect
import re

import pytest

from code_intelligence.agent import postprocess
from code_intelligence.agent.postprocess import build_final_response, _apply_backfill_chain

SCOPED = "SCOPED-OUTPUT"
RAW = "RAW-OUTPUT"

_SCOPED_ONLY_GUARDS = [
    "_backfill_missing_override_modules",
    "_correct_override_cascade_contradictions",
    "_backfill_missing_override_chain_amount",
    "_backfill_missing_trigger_condition_literals",
    "_backfill_missing_hardcoded_id_literals",
    "_backfill_missing_unguarded_super",
    "_backfill_link_guard_clarifications",
    "_flag_ungrounded_group_xmlids",
    "_backfill_missing_can_view_amount_fact",
]


@pytest.fixture
def recorded_calls(monkeypatch):
    calls = {}

    def install(name):
        def recorder(answer, *args, **kwargs):
            calls.setdefault(name, []).append(args)
            return answer
        recorder.__name__ = name
        monkeypatch.setattr(postprocess, name, recorder)

    for name in _SCOPED_ONLY_GUARDS:
        install(name)
    return calls


@pytest.mark.parametrize("guard_name", _SCOPED_ONLY_GUARDS)
def test_scoped_only_guards_receive_scoped_output(recorded_calls, guard_name):
    _apply_backfill_chain("answer", SCOPED, "question", raw_tool_output=RAW)
    assert recorded_calls.get(guard_name), f"{guard_name} was not called -- test is stale"
    for args in recorded_calls[guard_name]:
        assert args[0] == SCOPED, (
            f"{guard_name} received {args[0]!r} instead of the scoped output -- this reintroduces "
            "observations the fail-closed fix (section 492) is meant to drop"
        )


def test_build_final_response_feeds_the_chain_with_scoped_output():
    source = inspect.getsource(build_final_response)
    call = re.search(r"_apply_backfill_chain\(\s*final_answer,\s*(\w+),", source)
    assert call, "chain call not found in build_final_response source -- test is stale"
    assert call.group(1) == "scoped"


def test_applied_guards_lists_only_guards_that_changed_the_answer(monkeypatch):
    def changing_guard(answer, *args, **kwargs):
        return answer + "!"

    def neutral_guard(answer, *args, **kwargs):
        return answer

    monkeypatch.setattr(postprocess, "_backfill_missing_override_modules", changing_guard)
    monkeypatch.setattr(postprocess, "_flag_ungrounded_group_xmlids", neutral_guard)
    applied = []
    result = _apply_backfill_chain("answer", SCOPED, "question", raw_tool_output=RAW, applied_guards=applied)
    assert "changing_guard" in applied
    assert "neutral_guard" not in applied
    assert result.endswith("!")
