import importlib.util
import queue
from pathlib import Path

import pytest

from evaluation.erp_model_worker import classify_tool_observation

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_erp_model_eval.py"


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
        "category": "erp_chiffre",
        "question": "Combien de ventes ?",
        "expected_answer_contains": ["4", "Société Dupont"],
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
        "vram_fraction": 1.0,
    }
    return {**record, **changes}


def test_load_questions_selects_only_the_erp_benchmark(bench):
    questions = bench.load_questions(None)
    assert len(questions) == 15
    assert all(item["category"] == "erp_chiffre" for item in questions)
    assert [item["id"] for item in bench.load_questions(["ERP-01"])] == ["ERP-01"]
    assert bench.load_questions(["DOC-01"]) == []


def test_score_matches_expected_values_without_matching_inside_longer_numbers(bench):
    item = _item(expected_answer_contains=["4", "Société Dupont"])
    assert bench.score(item, "24 ventes pour Societe Dupont.") == {
        "fact_recall": 0.5,
        "complete": False,
    }
    assert bench.score(item, "4 ventes pour Société Dupont.") == {
        "fact_recall": 1.0,
        "complete": True,
    }


@pytest.mark.parametrize(
    ("observation", "status"),
    [
        ("12 records", "ok"),
        ("ORM read refused: access denied", "invalid"),
        ("ORM operation 'read' failed or was refused.", "invalid"),
        ("Tool 'missing_tool' is not available.", "unknown"),
    ],
)
def test_tool_observation_classification(observation, status):
    assert classify_tool_observation(observation) == status


def test_run_once_records_tool_and_loop_metrics(monkeypatch, bench):
    monkeypatch.setattr(
        bench,
        "_run_isolated_question",
        lambda *args: {
            "answer": "4 ventes pour Société Dupont.",
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
    assert result["no_tool"] is True


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
    assert bench._run_isolated_question("question", 7, "secret", "model", 0) == {
        "timed_out": True,
        "tool_calls": [],
        "llm_errors": [],
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
