import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_agent_variants_bench.py"


@pytest.fixture
def bench():
    spec = importlib.util.spec_from_file_location("run_agent_variants_bench_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(variant, questionId, passNumber, fallbackReason=None, error=None):
    return {"variant": variant, "question_id": questionId, "pass_number": passNumber,
            "fallback_reason": fallbackReason, "error": error,
            "hop_count": 2, "llm_call_count": 3, "seconds": 10.0}


def test_every_variant_question_pass_is_planned_once(bench):
    todo = list(bench.pending_runs(bench.VARIANT_NAMES, 3, {}, False))
    keys = [key for key, _ in todo]
    assert len(keys) == len(set(keys)) == len(bench.VARIANT_NAMES) * len(bench.QUESTIONS) * 3
    assert {question for _, question in todo} == set(bench.QUESTIONS.values())


def test_variant_order_rotates_between_questions(bench):
    firstVariants = {key[0] for key, _ in bench.pending_runs(bench.VARIANT_NAMES, 1, {}, False)
                     if key[1] in ("Q01", "Q02", "Q03")}
    assert len(firstVariants) == 3


def test_recorded_runs_are_skipped_and_infra_failures_retried_on_demand(bench):
    runs = {
        ("current", "Q01", 1): _record("current", "Q01", 1),
        ("temp06", "Q01", 1): _record("temp06", "Q01", 1, fallbackReason="interrupted"),
        ("no_think", "Q01", 1): _record("no_think", "Q01", 1, error="ConnectError: down"),
    }
    def pendingForQ01(retry):
        return {key for key, _ in bench.pending_runs(bench.VARIANT_NAMES, 1, runs, retry) if key[1] == "Q01"}

    assert pendingForQ01(False) == set()
    assert pendingForQ01(True) == {("temp06", "Q01", 1), ("no_think", "Q01", 1)}


def test_load_runs_keeps_the_latest_record_of_a_retried_run(bench, tmp_path):
    path = tmp_path / "runs.jsonl"
    lines = [_record("current", "Q01", 1, fallbackReason="interrupted"), _record("current", "Q01", 1)]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    assert bench.outcome(bench.load_runs(path)[("current", "Q01", 1)]) == bench.ANSWERED


def test_temp06_changes_only_the_temperature(bench, monkeypatch):
    received = []
    monkeypatch.setattr(bench.agentLoop, "get_chat_llm", lambda **kwargs: received.append(kwargs))
    with bench.variant_patch("temp06"):
        bench.agentLoop.get_chat_llm(temperature=0.0, max_tokens=4096)
    bench.agentLoop.get_chat_llm(temperature=0.0, max_tokens=4096)
    assert received == [{"temperature": 0.6, "max_tokens": 4096}, {"temperature": 0.0, "max_tokens": 4096}]


def test_no_think_appends_the_marker_to_the_system_prompt_then_restores_it(bench, monkeypatch):
    import core.llm.llm_client as llmClient
    monkeypatch.setattr(llmClient, "LLM_NO_THINK_MARKER", "/no_think")
    original = bench.agentLoop.SYSTEM_INVESTIGATION_PROMPT
    with bench.variant_patch("no_think"):
        assert bench.agentLoop.SYSTEM_INVESTIGATION_PROMPT == f"{original} /no_think"
    assert bench.agentLoop.SYSTEM_INVESTIGATION_PROMPT == original


def test_current_variant_changes_nothing(bench):
    original = (bench.agentLoop.get_chat_llm, bench.agentLoop.SYSTEM_INVESTIGATION_PROMPT)
    with bench.variant_patch("current"):
        assert (bench.agentLoop.get_chat_llm, bench.agentLoop.SYSTEM_INVESTIGATION_PROMPT) == original


def test_run_once_reads_the_fallback_from_the_logged_summary(bench, monkeypatch, tmp_path):
    from core.session.reasoning_trace_logger import ReasoningTraceLogger

    def fakeAgent(state):
        ReasoningTraceLogger(tmp_path / "trace.jsonl").log_summary(
            "t1", "code_intelligence", state["question"], 1, 2, 5.0, fallback_reason=bench.FALLBACK)
        return {}

    monkeypatch.setattr(bench.agentLoop, "code_intelligence_agent", fakeAgent)
    result = bench.run_once("comment voir les ventes ?")
    assert (result["fallback_reason"], result["hop_count"], result["llm_call_count"], result["error"]) == (
        bench.FALLBACK, 1, 2, None)


def test_run_once_records_an_agent_exception_as_error(bench, monkeypatch):
    def failingAgent(state):
        raise ConnectionError("tunnel down")

    monkeypatch.setattr(bench.agentLoop, "code_intelligence_agent", failingAgent)
    result = bench.run_once("question")
    assert result["error"].startswith("ConnectionError") and result["fallback_reason"] is None


def _bench_identity_vars():
    from erp_data.odoo_context import odoo_api_key_ctx, odoo_company_id_ctx, odoo_company_ids_ctx, odoo_uid_ctx
    return (odoo_uid_ctx, odoo_api_key_ctx, odoo_company_id_ctx, odoo_company_ids_ctx)


def test_requester_identity_needs_both_uid_and_api_key(bench, monkeypatch):
    for name in ("BENCH_ODOO_UID", "BENCH_ODOO_API_KEY", "BENCH_ODOO_COMPANY_ID"):
        monkeypatch.delenv(name, raising=False)
    assert bench.requester_identity() is None
    monkeypatch.setenv("BENCH_ODOO_UID", "12")
    assert bench.requester_identity() is None
    monkeypatch.setenv("BENCH_ODOO_API_KEY", "key")
    assert bench.requester_identity() == {"uid": 12, "api_key": "key", "company_id": None}
    monkeypatch.setenv("BENCH_ODOO_COMPANY_ID", "3")
    assert bench.requester_identity()["company_id"] == 3


def test_run_once_sets_the_identity_for_the_run_then_restores_it(bench, monkeypatch):
    seen = {}

    def fakeAgent(state):
        seen["values"] = tuple(variable.get() for variable in _bench_identity_vars())
        return {}

    monkeypatch.setattr(bench.agentLoop, "code_intelligence_agent", fakeAgent)
    result = bench.run_once("question", {"uid": 12, "api_key": "key", "company_id": 3})
    assert seen["values"] == (12, "key", 3, [3])
    assert result["orm_identity"] is True
    assert tuple(variable.get() for variable in _bench_identity_vars()) == (None, None, None, None)


def test_run_once_without_identity_sets_nothing_and_flags_the_record(bench, monkeypatch):
    seen = {}

    def fakeAgent(state):
        seen["values"] = tuple(variable.get() for variable in _bench_identity_vars())
        return {}

    monkeypatch.setattr(bench.agentLoop, "code_intelligence_agent", fakeAgent)
    result = bench.run_once("question")
    assert seen["values"] == (None, None, None, None)
    assert result["orm_identity"] is False


def test_identity_is_restored_when_the_agent_fails(bench, monkeypatch):
    def failingAgent(state):
        raise ConnectionError("tunnel down")

    monkeypatch.setattr(bench.agentLoop, "code_intelligence_agent", failingAgent)
    result = bench.run_once("question", {"uid": 12, "api_key": "key", "company_id": None})
    assert result["error"].startswith("ConnectionError")
    assert tuple(variable.get() for variable in _bench_identity_vars()) == (None, None, None, None)


def test_report_warns_about_runs_without_identity(bench, capsys):
    biased = _record("current", "Q01", 1, fallbackReason=bench.FALLBACK)
    sound = {**_record("current", "Q02", 1), "orm_identity": True}
    bench.print_report({("current", "Q01", 1): biased, ("current", "Q02", 1): sound}, ["current"])
    assert "1/2 run(s) had no requester identity" in capsys.readouterr().out
    bench.print_report({("current", "Q02", 1): sound}, ["current"])
    assert "no requester identity" not in capsys.readouterr().out


def test_variant_stats_counts_each_outcome_once(bench):
    records = [
        _record("current", "Q01", 1, fallbackReason=bench.FALLBACK),
        _record("current", "Q01", 2, fallbackReason=bench.FALLBACK),
        _record("current", "Q02", 1),
        _record("current", "Q02", 2, fallbackReason="interrupted"),
        _record("current", "Q03", 1, fallbackReason="incomplete_investigation"),
        _record("current", "Q03", 2, error="ConnectError"),
    ]
    stats = bench.variant_stats(records)
    assert (stats["runs"], stats["fallback"], stats["answered"], stats["infra"], stats["other"]) == (6, 2, 1, 2, 1)
    assert stats["llm_calls"] == 3.0
