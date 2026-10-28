import contextlib

import pytest

from core.evaluation import bench_common as common
from core.evaluation import run_store


def test_normalize_ignores_case_accents_spaces_and_emphasis():
    assert common.normalize("**48** Heures\u202fOuvrées") == common.normalize("48 heures ouvrees")
    assert common.normalize("d\u2019Identification") == common.normalize("d'identification")


def test_a_number_is_never_found_inside_a_longer_number():
    folded = common.normalize("moins de 24 heures, écart de 12 %")
    assert not common.contains_fact(folded, "4 heures")
    assert not common.contains_fact(folded, "2%")
    assert common.contains_fact(common.normalize("moins de **4 heures**, écart de 2 %"), "4 heures")


def test_latency_percentiles():
    assert common.latency_percentiles([float(number) for number in range(10, 0, -1)]) == (5.5, 9.0)
    assert common.latency_percentiles([]) == (None, None)


def test_context_length_must_match_the_comparison_configuration():
    common.require_context_length({"context_length": 32768}, 32768)
    with pytest.raises(common.BackendUnavailable, match="Expected Ollama context length 32768"):
        common.require_context_length({"context_length": 4096}, 32768)
    with pytest.raises(common.BackendUnavailable, match="got None"):
        common.require_context_length({}, 32768)


def test_rescore_runs_updates_the_runs_without_error_only():
    runs = {("m", "Q1", 1): {"question_id": "Q1", "error": None, "score": 0},
            ("m", "Q1", 2): {"question_id": "Q1", "error": "x", "score": 0},
            ("m", "Gone", 1): {"question_id": "Gone", "error": None, "score": 0}}
    common.rescore_runs(runs, [{"id": "Q1"}], lambda item, record: {"score": 1})
    assert [record["score"] for record in runs.values()] == [1, 0, 0]


def _execute(tmp_path, failures):
    outcomes = iter(failures)
    todo = [({"id": f"Q{number}"}, 1) for number in range(len(failures))]
    runs = {}
    build = lambda item, passNumber: {"model": "m", "question_id": item["id"], "pass_number": passNumber,
                                      "error": "x" if next(outcomes) else None, "seconds": 1.0}
    return common.execute_runs(todo, runs, tmp_path / "runs.jsonl", build, lambda record: "done"), runs


def test_execute_runs_stops_after_three_consecutive_errors(tmp_path):
    finished, runs = _execute(tmp_path, [True] * 5)
    assert finished is False
    assert len(runs) == common.MAX_CONSECUTIVE_ERRORS
    assert len(run_store.load_runs(tmp_path / "runs.jsonl")) == common.MAX_CONSECUTIVE_ERRORS


def test_execute_runs_resets_the_error_counter_after_a_success(tmp_path):
    finished, runs = _execute(tmp_path, [True, True, False, True, True])
    assert finished is True
    assert len(runs) == 5


@pytest.fixture
def server(monkeypatch):
    calls = {"unloaded": []}
    monkeypatch.setattr(common, "prepare_server", lambda model: {"vram_fraction": 1.0, "context_length": 32768})
    monkeypatch.setattr(common, "set_keep_alive", lambda model, keepAlive: calls["unloaded"].append((model, keepAlive)))
    monkeypatch.setattr(common, "model_override", lambda model: contextlib.nullcontext())
    monkeypatch.setattr(common, "require_backends", lambda probes=None: calls.setdefault("probes", probes))
    return calls


def test_run_on_model_runs_then_unloads_the_model(server):
    seen = []
    assert common.run_on_model("m", 32768, False, lambda info: seen.append(info) or True, probes={"llm": None}) == 0
    assert seen == [{"vram_fraction": 1.0, "context_length": 32768}]
    assert server["unloaded"] == [("m", 0)]
    assert server["probes"] == {"llm": None}


def test_run_on_model_keeps_the_model_loaded_on_request(server):
    assert common.run_on_model("m", 32768, True, lambda info: True) == 0
    assert server["unloaded"] == []


def test_run_on_model_reports_an_interrupted_run(server):
    assert common.run_on_model("m", 32768, False, lambda info: False) == 3


def test_run_on_model_refuses_a_context_length_mismatch_before_any_run(server):
    assert common.run_on_model("m", 4096, False, lambda info: pytest.fail("must not run")) == 3
    assert server["unloaded"] == [("m", 0)]


def test_run_on_model_skips_a_model_the_server_cannot_load(monkeypatch, server):
    def refuse(model):
        raise common.BackendUnavailable("not pulled")

    monkeypatch.setattr(common, "prepare_server", refuse)
    assert common.run_on_model("m", 32768, False, lambda info: pytest.fail("must not run")) == 2
    assert server["unloaded"] == []
