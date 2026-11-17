from unittest.mock import MagicMock

import pytest

from core.session import reasoning_trace_logger as module
from core.session.reasoning_trace_logger import ReasoningTraceLogger, finish_branch


@pytest.fixture
def default_path(tmp_path, monkeypatch):
    path = tmp_path / "captures" / "reasoning_trace.jsonl"
    monkeypatch.setattr(module, "DEFAULT_LOG_PATH", path)
    return path


def _log_one_hop(logger):
    logger.log_hop("t1", 1, "search_read", {"model": "res.partner"}, "obs", 1.0)


def test_nothing_is_written_by_default(default_path, monkeypatch):
    monkeypatch.setattr(module, "REASONING_TRACE_ENABLED", False)
    logger = ReasoningTraceLogger()
    _log_one_hop(logger)
    assert not default_path.parent.exists()
    assert logger.read_recent() == []


def test_setting_turns_the_default_file_on(default_path, monkeypatch):
    monkeypatch.setattr(module, "REASONING_TRACE_ENABLED", True)
    logger = ReasoningTraceLogger()
    _log_one_hop(logger)
    assert [record["tool_name"] for record in logger.read_recent()] == ["search_read"]


def test_an_explicit_file_is_always_written(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "REASONING_TRACE_ENABLED", False)
    logger = ReasoningTraceLogger(log_filepath=tmp_path / "own.jsonl")
    _log_one_hop(logger)
    assert len(logger.read_trace("t1")) == 1


def test_finish_branch_without_hops_keeps_the_state_timing_and_logs_zero_hops():
    trace_logger = MagicMock()
    timing = finish_branch(trace_logger, "t1", "documentation", "q", {"timing": {"retrieval_time": 1}}, 0.0, 2)
    assert timing["retrieval_time"] == 1
    assert timing["llm_call_count"] == 2
    assert timing["generation_time"] > 0
    assert "hop_count" not in timing
    summary = trace_logger.log_summary.call_args.kwargs
    assert (summary["hop_count"], summary["llm_call_count"], summary["hop_cap"]) == (0, 2, None)


def test_finish_branch_with_hops_records_them_in_timing_and_summary():
    trace_logger = MagicMock()
    timing = finish_branch(trace_logger, "t1", "system", "q", {}, 0.0, 3, hops=2, hop_cap=5)
    assert timing["hop_count"] == 2
    summary = trace_logger.log_summary.call_args.kwargs
    assert (summary["hop_count"], summary["hop_cap"], summary["branch"]) == (2, 5, "system")
