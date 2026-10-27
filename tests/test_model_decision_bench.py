import importlib.util
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_model_decision_bench.py"


@pytest.fixture
def bench(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_model_decision_bench_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "RESULTS_PATH", tmp_path / "results.jsonl")
    return module


def _record(model="m1", questionId="Q1", passNumber=1, **fields):
    base = {
        "model": model, "question_id": questionId, "pass_number": passNumber,
        "error": None, "fallback_reason": None, "missing_tools": [], "tool_results": {"ok": 2},
        "hop_count": 2, "llm_call_count": 3, "seconds": 10.0, "vram_fraction": 1.0,
    }
    return {**base, **fields}


def _outcome(**fields):
    identity = ("model", "question_id", "pass_number")
    return {key: value for key, value in _record(**fields).items() if key not in identity}


def _write(bench, records):
    with open(bench.RESULTS_PATH, "w", encoding="utf-8") as file:
        file.writelines(json.dumps(record) + "\n" for record in records)


def _tool_message(content, status="success"):
    return ToolMessage(content=content, tool_call_id="id", status=status)


@pytest.mark.parametrize("message, kind", [
    (_tool_message("Tool unavailable."), "invalid"),
    (_tool_message("Field x is required", status="error"), "invalid"),
    (_tool_message("Error executing search_system; no conclusion can be drawn from this failure."), "failed"),
    (_tool_message("Already executed; use the earlier observation."), "duplicate"),
    (_tool_message("Refused: undeclared security principal."), "refused"),
    (_tool_message("Investigation tool budget exhausted."), "budget"),
    (_tool_message("Observation budget exhausted."), "budget"),
    (_tool_message("Model 'x.y' was not found in the indexed knowledge graph"), "not_found"),
    (_tool_message("fields: name, state"), "ok"),
])
def test_observations_are_classified(bench, message, kind):
    assert bench.classify(message) == kind


def test_tool_call_stats_counts_attempts_and_results(bench):
    messages = [
        AIMessage(content="", tool_calls=[{"name": "search_system", "args": {}, "id": "a"}]),
        _tool_message("fields: name"),
        AIMessage(content="", tool_calls=[{"name": "search_system", "args": {}, "id": "b"},
                                          {"name": "fields_get", "args": {}, "id": "c"}]),
        _tool_message("Already executed; use the earlier observation."),
        _tool_message("Tool unavailable."),
        AIMessage(content="answer"),
    ]
    attempted, results = bench.tool_call_stats(messages)
    assert attempted == ["search_system", "search_system", "fields_get"]
    assert results == {"ok": 1, "duplicate": 1, "invalid": 1}


def test_pending_runs_skip_recorded_and_retry_infrastructure_failures_only_on_request(bench):
    questions = [{"id": "Q1"}, {"id": "Q2"}, {"id": "Q3"}]
    runs = {
        ("m1", "Q1", 1): _record(questionId="Q1"),
        ("m1", "Q2", 1): _record(questionId="Q2", error="APITimeoutError"),
        ("m1", "Q3", 1): _record(questionId="Q3", fallback_reason="interrupted"),
    }
    plain = [(item["id"], number) for item, number in bench.pending_runs("m1", questions, 2, runs, False)]
    retry = [(item["id"], number) for item, number in bench.pending_runs("m1", questions, 2, runs, True)]
    assert plain == [("Q1", 2), ("Q2", 2), ("Q3", 2)]
    assert retry == [("Q2", 1), ("Q3", 1), ("Q1", 2), ("Q2", 2), ("Q3", 2)]
    assert [item["id"] for item, _ in bench.pending_runs("other", questions, 1, runs, False)] == ["Q1", "Q2", "Q3"]


def test_discard_model_keeps_the_other_models(bench):
    _write(bench, [_record("m1"), _record("m2"), _record("m1", "Q2")])
    bench.discard_model("m1")
    assert list(bench.load_runs()) == [("m2", "Q1", 1)]


def test_load_runs_keeps_the_latest_record_of_a_run(bench):
    _write(bench, [_record(error="boom"), _record(seconds=5.0)])
    runs = bench.load_runs()
    assert len(runs) == 1 and runs[("m1", "Q1", 1)]["error"] is None


def test_model_stats_exclude_infrastructure_failures_from_rates(bench):
    records = [
        _record(questionId="Q1"),
        _record(questionId="Q2", missing_tools=["fields_get"], fallback_reason=bench.FALLBACK,
                tool_results={"ok": 1, "invalid": 1, "not_found": 2}, seconds=30.0, vram_fraction=0.8),
        _record(questionId="Q3", error="ConnectionError", tool_results={}),
        _record(questionId="Q4", fallback_reason="interrupted", tool_results={}),
    ]
    stats = bench.model_stats(records)
    assert (stats["runs"], stats["infra"]) == (4, 2)
    assert stats["coverage"] == 0.5 and stats["fallback"] == 0.5
    assert (stats["calls"], stats["bad"], stats["not_found"]) == (6, 1, 2)
    assert stats["ok"] == pytest.approx(3 / 6)
    assert (stats["p50"], stats["p90"]) == (20.0, 30.0)
    assert stats["vram"] == 0.8


def test_model_stats_without_valid_run_does_not_divide_by_zero(bench):
    stats = bench.model_stats([_record(error="ConnectionError", tool_results={})])
    assert stats["coverage"] == 0.0 and stats["p50"] == 0.0 and stats["vram"] == 1.0


def test_execute_appends_each_result_and_stops_after_consecutive_infrastructure_failures(monkeypatch, bench):
    items = [{"id": f"Q{number}", "bank": "b", "capability": "c", "expected_tools": ["t"]} for number in range(5)]
    outcomes = iter([_outcome(), _outcome(error="down"), _outcome(error="down"), _outcome(error="down"), _outcome()])
    monkeypatch.setattr(bench, "run_once", lambda item: next(outcomes))
    runs = {}
    finished = bench.execute([(item, 1) for item in items], runs, "m1", {"vram_fraction": 1.0, "context_length": 8})
    lines = bench.RESULTS_PATH.read_text(encoding="utf-8").splitlines()
    assert finished is False
    assert len(lines) == bench.MAX_CONSECUTIVE_INFRA_FAILURES + 1
    assert json.loads(lines[0])["question_id"] == "Q0" and json.loads(lines[0])["expected_tools"] == ["t"]


def test_execute_resets_the_failure_counter_after_a_success(monkeypatch, bench):
    items = [{"id": f"Q{number}", "bank": "b", "capability": "c"} for number in range(5)]
    outcomes = iter([_outcome(error="down"), _outcome(error="down"), _outcome(), _outcome(error="down"), _outcome(error="down")])
    monkeypatch.setattr(bench, "run_once", lambda item: next(outcomes))
    assert bench.execute([(item, 1) for item in items], {}, "m1", {}) is True


def test_recording_agent_stores_the_final_messages_of_each_invocation(bench):
    class Agent:
        def invoke(self, *args, **kwargs):
            return {"messages": ["final"]}

    box = []
    result = bench.RecordingAgent(Agent(), box).invoke({"messages": []})
    assert result == {"messages": ["final"]} and box == [["final"]]


def test_capture_agent_messages_wraps_create_react_agent_and_restores_it(bench):
    import langgraph.prebuilt

    original = langgraph.prebuilt.create_react_agent
    box = []
    with bench.capture_agent_messages(box):
        assert langgraph.prebuilt.create_react_agent is not original
    assert langgraph.prebuilt.create_react_agent is original
