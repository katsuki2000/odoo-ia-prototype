import importlib.util
import queue
from pathlib import Path

import pytest

from evaluation.erp_model_worker import classify_tool_observation, describe_tool_call

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "run_erp_model_eval.py"


@pytest.fixture
def bench(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_erp_model_eval_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "RESULTS_PATH", tmp_path / "results.jsonl")
    return module


def _item(**changes):
    return {
        "id": "ERP-01",
        "question": "Combien de ventes ?",
        "expected": [["4"], ["Société Dupont"]],
        **changes,
    }


def _record(**changes):
    record = {
        "model": "qwen3:8b",
        "question_id": "ERP-01",
        "pass_number": 1,
        "answer": "4 ventes pour Société Dupont.",
        "answer_chars": 30,
        "tool_calls": [{"name": "search_read", "status": "ok"}],
        "tool_call_count": 1,
        "tool_ok": 1,
        "tool_invalid": 0,
        "tool_unknown": 0,
        "no_tool": False,
        "llm_calls": 2,
        "llm_error_count": 0,
        "hops": 1,
        "seconds": 10.0,
        "timed_out": False,
        "error": None,
        "fact_recall": 1.0,
        "complete": True,
        "expected": [["4"]],
        "vram_fraction": 1.0,
    }
    return {**record, **changes}


def test_load_questions_reads_the_erp_bank_and_filters_by_id(bench):
    questions = bench.load_questions(None)
    assert len(questions) == 16
    assert all("expectation" in item for item in questions)
    assert [item["id"] for item in bench.load_questions(["ERP-01"])] == ["ERP-01"]
    assert bench.load_questions(["DOC-01"]) == []


def test_score_needs_one_writing_per_expected_group_without_matching_inside_longer_numbers(bench):
    expected = [["4"], ["Société Dupont"]]
    assert bench.score(expected, "24 ventes pour Societe Dupont.") == {"fact_recall": 0.5, "complete": False}
    assert bench.score(expected, "4 ventes pour Société Dupont.") == {"fact_recall": 1.0, "complete": True}
    amount = [["120187,11", "120187.11"]]
    assert bench.score(amount, "Total : 120 187.11 Ar")["complete"] is True


@pytest.mark.parametrize(
    ("record", "retry"),
    [
        ({"error": "ValueError", "complete": False}, True),
        ({"error": None, "timed_out": True, "complete": False}, True),
        ({"error": None, "timed_out": False, "complete": False}, True),
        ({"error": None, "timed_out": False, "complete": True}, False),
    ],
)
def test_retry_errors_selects_every_unsuccessful_run(bench, record, retry):
    assert bench.retryable_run(record) is retry


def test_rerun_selects_requested_passes_without_removing_existing_records(bench):
    questions = [_item(), _item(id="ERP-02")]
    completed = {
        ("qwen3:8b", item["id"], pass_number): {
            "question_id": item["id"], "pass_number": pass_number, "complete": True, "error": None,
        }
        for item in questions
        for pass_number in (1, 2)
    }

    assert bench.select_pending_runs("qwen3:8b", questions, 2, completed) == []
    assert bench.select_pending_runs("qwen3:8b", questions, 2, completed, rerun=True) == [
        (questions[0], 1), (questions[1], 1),
        (questions[0], 2), (questions[1], 2),
    ]
    assert len(completed) == 4


def test_attach_expected_keeps_applicable_questions_and_reports_the_others(monkeypatch, bench, capsys):
    def compute(execute, item):
        if item["id"] == "ERP-02":
            raise bench.NotApplicable("module purchase is not installed")
        return [["4"]]

    monkeypatch.setattr(bench, "compute_expected", compute)
    first, second = _item(id="ERP-01"), _item(id="ERP-02")
    todo = [(first, 1), (second, 1), (first, 2), (second, 2)]
    assert bench.attach_expected(todo, execute=None) == [(first, 1), (first, 2)]
    assert first["expected"] == [["4"]]
    assert "[SKIP] ERP-02: module purchase is not installed" in capsys.readouterr().out


def test_rescoring_uses_the_value_recorded_with_the_run(bench, tmp_path):
    record = _record(expected=[["7"]], answer="Il y en a 4.", fact_recall=1.0, complete=True)
    bench.run_store.append_run(bench.RESULTS_PATH, record)
    (rescored,) = bench.load_scored_runs().values()
    assert (rescored["fact_recall"], rescored["complete"]) == (0.0, False)


@pytest.mark.parametrize(
    ("observation", "status"),
    [
        ("12 records", "ok"),
        ("ORM read refused: access denied", "invalid"),
        ("ORM operation 'read' failed or was refused.", "invalid"),
        ("Query refused: invalid arguments for list_models: query: Field required", "invalid"),
        ("Tool 'missing_tool' is not available.", "unknown"),
    ],
)
def test_tool_observation_classification(observation, status):
    assert classify_tool_observation(observation) == status


def test_describe_tool_call_keeps_the_arguments_and_the_error_of_refused_calls_only():
    assert describe_tool_call("search_count", {"model": "m"}, "12 records") == {
        "name": "search_count", "status": "ok", "args": {"model": "m"}}
    refused = describe_tool_call("read_group", {"groupby": []}, "ORM read refused: " + "x" * 500)
    assert refused["status"] == "invalid" and refused["args"] == {"groupby": []}
    assert refused["error"].startswith("ORM read refused:") and len(refused["error"]) == 300


def test_describe_tool_call_records_covers_plan_for_successful_domain_reads_only():
    assert describe_tool_call("search_count", {}, "12 records", True)["covers_plan"] is True
    assert describe_tool_call("search_read", {}, "3 records", False)["covers_plan"] is False
    assert "covers_plan" not in describe_tool_call("search_count", {}, "12 records")
    assert "covers_plan" not in describe_tool_call("fields_get", {}, "{}", False)
    assert "covers_plan" not in describe_tool_call("search_count", {}, "ORM read refused: denied", True)
    assert "covers_plan" not in describe_tool_call("missing", {}, "Tool 'missing' is not available.", True)


def test_describe_tool_call_records_the_row_count_when_known():
    assert describe_tool_call("list_models", {"query": "x"}, "ok", row_count=0)["row_count"] == 0
    assert "row_count" not in describe_tool_call("list_models", {"query": "x"}, "ok")


def test_benchmark_records_keep_the_call_shape_but_no_data_value():
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "run_erp_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_erp_benchmark_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = [
        {"name": "search_count", "status": "ok", "covers_plan": True, "row_count": 1, "args": {
            "model": "account.move", "domain": [("state", "=", "secret"), "|", ["move_type", "in", ["a", "b"]]]}},
        {"name": "list_models", "status": "ok", "row_count": 0, "args": {"query": "paiement"}},
        {"name": "name_search", "status": "ok", "args": {"model": "res.partner", "name": "Acme"}},
        {"name": "read", "status": "invalid", "error": "refused", "args": {"ids": [7], "fields": ["name"]}},
    ]
    assert module._safe_tool_calls(calls) == [
        {"name": "search_count", "status": "ok", "row_count": 1, "covers_plan": True,
         "model": "account.move", "domain": [["state", "="], "|", ["move_type", "in"]]},
        {"name": "list_models", "status": "ok", "row_count": 0, "query": "paiement"},
        {"name": "name_search", "status": "ok", "model": "res.partner"},
        {"name": "read", "status": "invalid", "error": "refused"},
    ]


def test_run_once_records_tool_and_loop_metrics(monkeypatch, bench):
    monkeypatch.setattr(
        bench,
        "_run_isolated_question",
        lambda *args: {
            "answer": "4 ventes pour Société Dupont.",
            "model_answer": "Précisez la période.",
            "query_plan": {"subject": "ventes", "conditions": ["confirmées"]},
            "timing": {"llm_call_count": 3, "hop_count": 2},
            "tool_calls": [
                {"name": "search_read", "status": "ok"},
                {"name": "read_group", "status": "invalid"},
                {"name": "unknown", "status": "unknown"},
            ],
            "llm_errors": [],
        },
    )
    result = bench.run_once(_item(), 7, "secret", "qwen3:8b")
    assert result["fact_recall"] == 1.0
    assert result["model_answer"] == "Précisez la période."
    assert result["query_plan"] == {"subject": "ventes", "conditions": ["confirmées"]}
    assert (result["tool_call_count"], result["tool_ok"], result["tool_invalid"], result["tool_unknown"]) == (3, 1, 1, 1)
    assert (result["no_tool"], result["llm_calls"], result["hops"], result["error"]) == (False, 3, 2, None)


def test_run_once_keeps_a_timeout_distinct_from_backend_errors(monkeypatch, bench):
    monkeypatch.setattr(bench, "_run_isolated_question", lambda *args: {"timed_out": True})
    result = bench.run_once(_item(), 7, "secret", "qwen3:8b")
    assert result["timed_out"] is True
    assert result["error"] is None
    assert result["fact_recall"] == 0


def test_run_once_marks_a_network_failure_as_an_error(monkeypatch, bench):
    monkeypatch.setattr(
        bench,
        "_run_isolated_question",
        lambda *args: {
            "answer": "No data",
            "timing": {},
            "tool_calls": [],
            "llm_errors": [{"module": "openai", "type": "APIConnectionError"}],
        },
    )
    result = bench.run_once(_item(), 7, "secret", "qwen3:8b")
    assert result["error"] == "APIConnectionError (openai)"
    assert result["backend_error"] is True
    assert result["no_tool"] is True


def test_run_once_keeps_a_worker_exception_distinct_from_a_backend_error(monkeypatch, bench):
    monkeypatch.setattr(bench, "_run_isolated_question", lambda *args: {
        "worker_error": "ValueError",
        "worker_error_detail": "tool call result shape was rejected",
        "worker_traceback": "Traceback (most recent call last): ...",
        "timing": {"llm_call_count": 2, "hop_count": 1},
        "tool_calls": [{"name": "list_models", "status": "ok", "args": {"query": "invoice"}}],
        "llm_errors": [],
    })

    result = bench.run_once(_item(), 7, "secret", "qwen3:8b")

    assert result["error"] == "ValueError"
    assert result["backend_error"] is False
    assert result["worker_error_detail"] == "tool call result shape was rejected"
    assert result["worker_traceback"].startswith("Traceback")
    assert result["llm_calls"] == 2


def test_worker_timeout_terminates_the_question_process(monkeypatch, bench):
    class FakeQueue:
        def get_nowait(self):
            raise queue.Empty

        def close(self):
            pass

        def join_thread(self):
            pass

    class FakeProcess:
        def __init__(self, **kwargs):
            self.alive = False
            self.terminated = False

        def start(self):
            self.alive = True

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True
            self.alive = False

    class FakeContext:
        Queue = FakeQueue

        @staticmethod
        def Process(**kwargs):
            process = FakeProcess(**kwargs)
            processes.append(process)
            return process

    processes = []
    monkeypatch.setattr(bench.multiprocessing, "get_context", lambda method: FakeContext())
    assert bench._run_isolated_question("question", 7, "secret", "model", None, 0) == {
        "timed_out": True,
        "tool_calls": [],
        "llm_errors": [],
        "query_plan": None,
        "timing": {"llm_call_count": 0, "hop_count": 0},
    }
    assert processes[0].terminated is True


def test_authentication_uses_the_explicit_benchmark_identity(monkeypatch, bench):
    calls = []

    class Connector:
        def __init__(self, db, password):
            self.db = db
            calls.append(("connector", db, password))
            self.common = self

        def authenticate(self, db, login, password, context):
            calls.append((db, login, password, context))
            return 17

    monkeypatch.setattr(bench, "OdooConnector", Connector)
    monkeypatch.setattr(bench.settings, "ODOO_DB", "odoo-test")
    assert bench.authenticate_odoo("analyst@example.test", "secret") == 17
    assert calls == [
        ("connector", "odoo-test", "secret"),
        ("odoo-test", "analyst@example.test", "secret", {}),
    ]


def test_model_stats_separate_timeouts_errors_and_tool_use(bench):
    records = [
        _record(),
        _record(question_id="ERP-02", fact_recall=0.5, complete=False, no_tool=True, seconds=20.0),
        _record(question_id="ERP-03", timed_out=True, no_tool=None, seconds=90.0, fact_recall=0.0, complete=False, error=None),
        _record(question_id="ERP-04", error="APIConnectionError"),
    ]
    stats = bench.model_stats(records)
    assert (stats["runs"], stats["errors"], stats["timed_out"]) == (4, 1, 1 / 3)
    assert (stats["facts"], stats["complete"], stats["no_tool"]) == (0.5, 1 / 3, 0.5)
    assert (stats["p50"], stats["p90"]) == (20.0, 90.0)


def test_report_includes_model_and_per_question(capsys, bench):
    bench.print_report({("qwen3:8b", "ERP-01", 1): _record()})
    output = capsys.readouterr().out
    assert "qwen3:8b" in output
    assert "ERP-01" in output
    assert "noTool" in output


def test_main_requires_explicit_login_for_a_live_run(bench):
    with pytest.raises(SystemExit) as error:
        bench.main(["--model", "qwen3:8b"])
    assert error.value.code == 2


def test_the_reasoning_effort_reaches_the_isolated_worker(monkeypatch, bench):
    seen = []
    monkeypatch.setattr(bench, "_run_isolated_question", lambda *args: seen.append(args) or {"answer": ""})
    bench.run_once(_item(), 7, "secret", "qwen3:14b", "none")
    assert seen[0][3:5] == ("qwen3:14b", "none")


def test_results_are_recorded_under_the_model_and_its_reasoning_effort(monkeypatch, bench):
    monkeypatch.setattr(bench, "run_once", lambda item, uid, password, model, effort: {"seconds": 1.0})
    monkeypatch.setattr(bench, "execute_runs", lambda todo, runs, path, build_record, describe: build_record(*todo[0]))
    record = bench.run_questions([(_item(), 1)], {}, "qwen3:14b", "none", {}, 7, "secret")
    assert record["model"] == "qwen3:14b+reasoning_none"
    record = bench.run_questions([(_item(), 1)], {}, "qwen3:14b", None, {}, 7, "secret")
    assert record["model"] == "qwen3:14b"
