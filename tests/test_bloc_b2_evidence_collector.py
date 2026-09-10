"""
tests/test_bloc_b2_evidence_collector.py

Bloc B2 (todo/contexte.txt section 622) -- unit tests for the turn-scoped
Evidence accumulator in core/evidence_collector.py, in isolation, before
any real tool wrapper is wired to it. Pure unit tests, no Odoo/LLM
dependency.
"""

import logging

import pytest

from core.evidence import Evidence, EvidenceSourceType, make_evidence
from core.evidence_collector import (
    _turn_evidence_ctx,
    start_evidence_collection,
    record_evidence,
    collect_and_clear_evidence,
)


@pytest.fixture(autouse=True)
def _reset_turn_evidence_ctx():
    """The accumulator is a process-global ContextVar, not per-test --
    without this, a test executed earlier in the same pytest process
    (leaving a non-None bucket) could make an unrelated test's 'no active
    turn' assertion fail depending on collection order. Reset before AND
    after each test so this file's own execution order doesn't matter
    either."""
    _turn_evidence_ctx.set(None)
    yield
    _turn_evidence_ctx.set(None)


def _make(claim: str) -> Evidence:
    return make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=claim,
        source="test:fixture",
        value=1,
        scope={},
    )


def test_collect_without_start_returns_empty():
    # No start_evidence_collection() call at all in this test -- a stray
    # collect must not blow up, just return nothing.
    assert collect_and_clear_evidence() == []


def test_record_single_evidence_is_collected():
    start_evidence_collection()
    record_evidence(_make("fact A"))
    result = collect_and_clear_evidence()
    assert len(result) == 1
    assert result[0].claim == "fact A"


def test_record_list_of_evidence_extends_bucket():
    start_evidence_collection()
    record_evidence([_make("fact A"), _make("fact B")])
    result = collect_and_clear_evidence()
    assert len(result) == 2
    assert {e.claim for e in result} == {"fact A", "fact B"}


def test_record_mixes_single_and_list_across_calls():
    start_evidence_collection()
    record_evidence(_make("fact A"))
    record_evidence([_make("fact B"), _make("fact C")])
    record_evidence(_make("fact D"))
    result = collect_and_clear_evidence()
    assert [e.claim for e in result] == ["fact A", "fact B", "fact C", "fact D"]


def test_record_none_is_a_no_op():
    start_evidence_collection()
    record_evidence(None)
    assert collect_and_clear_evidence() == []


def test_collect_and_clear_resets_accumulator():
    start_evidence_collection()
    record_evidence(_make("fact A"))
    first = collect_and_clear_evidence()
    assert len(first) == 1
    # Second collect right after, with no new start_evidence_collection(),
    # must come back empty -- proves the accumulator was actually reset to
    # None (not left as []) rather than silently continuing to accept
    # writes for a turn that already ended.
    second = collect_and_clear_evidence()
    assert second == []


def test_new_turn_after_previous_collect_starts_fresh():
    start_evidence_collection()
    record_evidence(_make("turn 1 fact"))
    collect_and_clear_evidence()

    start_evidence_collection()
    record_evidence(_make("turn 2 fact"))
    result = collect_and_clear_evidence()
    assert len(result) == 1
    assert result[0].claim == "turn 2 fact"


def test_record_before_start_logs_warning_and_drops(caplog):
    # Simulate a tool invoked outside the normal turn lifecycle (e.g. a
    # script or a test exercising the wrapper directly) -- must not raise,
    # must warn, must not silently start a bucket.
    with caplog.at_level(logging.WARNING):
        record_evidence(_make("orphan fact"))
    assert "before start_evidence_collection" in caplog.text
    assert collect_and_clear_evidence() == []
