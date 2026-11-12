import pytest

from core.session import reasoning_trace_logger as module
from core.session.reasoning_trace_logger import ReasoningTraceLogger


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
