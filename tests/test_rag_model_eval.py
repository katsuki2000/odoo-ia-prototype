import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation import bench_common

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_rag_model_eval.py"
QUESTIONS = json.loads((Path(__file__).resolve().parent / "rag_eval_questions.json").read_text(encoding="utf-8"))["questions"]


@pytest.fixture
def bench(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_rag_model_eval_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "RESULTS_PATH", tmp_path / "results.jsonl")
    monkeypatch.setattr(module, "CONTEXTS_PATH", tmp_path / "contexts.json")
    return module


def _item(**fields):
    base = {"id": "Q1", "category": "single_fact", "answerable": True, "question": "Quel plafond ?",
            "facts": ["48 heures ouvrées"], "reference_sources": ["guide.docx"]}
    return {**base, **fields}


def _trap():
    return _item(id="TRAP", category="unanswerable", answerable=False, facts=[], reference_sources=[])


def _record(model="m1", question_id="Q1", pass_number=1, **fields):
    base = {
        "model": model, "question_id": question_id, "pass_number": pass_number, "answerable": True, "error": None,
        "fact_recall": 1.0, "source_recall": 1.0, "abstained": False, "structured_failed": False,
        "seconds": 10.0, "vram_fraction": 1.0, "confidence": 0.9, "answer_chars": 40,
    }
    return {**base, **fields}


def _response(answer, titles=(), confidence=0.9):
    return SimpleNamespace(answer=answer, confidence=confidence, sources=[SimpleNamespace(title=title) for title in titles])


def test_normalize_ignores_case_accents_spaces_and_emphasis(bench):
    assert bench.normalize("**48** Heures\u202fOuvrées") == bench.normalize("48 heures ouvrees")
    assert bench.normalize("d’Identification") == bench.normalize("d'identification")


def test_score_counts_found_facts_and_cited_reference_sources(bench):
    item = _item(facts=["25 du mois", "48 heures ouvrées"], reference_sources=["a.txt", "b.pdf"])
    scored = bench.score(item, "Avant le **25 du mois**, validation en 48 heures.", ["a.txt", "other.txt"])
    assert scored == {"fact_recall": 0.5, "source_recall": 0.5, "abstained": False}


def test_score_of_an_unanswerable_question_has_no_recall(bench):
    scored = bench.score(_trap(), "Je n'ai pas trouvé cette information dans la base de connaissance interne.", [])
    assert scored == {"fact_recall": None, "source_recall": None, "abstained": True}


def test_a_numeric_fact_is_not_found_inside_a_longer_number(bench):
    item = _item(facts=["4 heures", "2%"], reference_sources=[])
    assert bench.score(item, "P4 : moins de 24 heures, écart de 12 %.", [])["fact_recall"] == 0.0
    assert bench.score(item, "P3 : moins de **4 heures**, écart de 2 %.", [])["fact_recall"] == 1.0


def test_load_scored_runs_recomputes_scores_and_skips_errors(monkeypatch, bench):
    monkeypatch.setattr(bench, "load_questions", lambda ids: [_item()])
    stored = {"answer": "Validation en 48 heures ouvrées.", "cited_sources": ["guide.docx"], "fact_recall": 0.0, "source_recall": 0.0}
    bench.run_store.append_run(bench.RESULTS_PATH, _record(**stored))
    bench.run_store.append_run(bench.RESULTS_PATH, _record(pass_number=2, error="x", **stored))
    runs = bench.load_scored_runs()
    assert (runs[("m1", "Q1", 1)]["fact_recall"], runs[("m1", "Q1", 1)]["source_recall"]) == (1.0, 1.0)
    assert runs[("m1", "Q1", 2)]["fact_recall"] == 0.0


def test_every_fact_of_the_question_set_is_found_in_its_own_reference(bench):
    for item in QUESTIONS:
        if item["answerable"]:
            assert bench.score(item, item["reference"], item["reference_sources"])["source_recall"] == 1.0
    multi = next(item for item in QUESTIONS if item["id"] == "MULTI-01")
    assert bench.score(multi, multi["reference"], [])["fact_recall"] == 1.0


def test_load_contexts_retrieves_once_and_reuses_the_cache(monkeypatch, bench):
    calls = []
    monkeypatch.setattr(bench, "retrieve", lambda state: calls.append(state["question"]) or {"retrieved_chunks": [{"document": "d"}]})
    questions = [_item(id="Q1"), _item(id="Q2", question="Autre ?")]
    assert bench.load_contexts(questions, refresh=False) == {"Q1": [{"document": "d"}], "Q2": [{"document": "d"}]}
    bench.load_contexts(questions, refresh=False)
    assert len(calls) == 2


def test_load_contexts_retrieves_again_when_the_question_changes_or_on_refresh(monkeypatch, bench):
    calls = []
    monkeypatch.setattr(bench, "retrieve", lambda state: calls.append(state["question"]) or {"retrieved_chunks": [{"document": "d"}]})
    bench.load_contexts([_item()], refresh=False)
    bench.load_contexts([_item(question="Reformulée ?")], refresh=False)
    bench.load_contexts([_item(question="Reformulée ?")], refresh=True)
    assert calls == ["Quel plafond ?", "Reformulée ?", "Reformulée ?"]


def test_load_contexts_keeps_the_cache_of_questions_outside_the_filter(monkeypatch, bench):
    monkeypatch.setattr(bench, "retrieve", lambda state: {"retrieved_chunks": [{"document": state["question"]}]})
    bench.load_contexts([_item(id="Q1"), _item(id="Q2", question="Autre ?")], refresh=False)
    bench.load_contexts([_item(id="Q1")], refresh=True)
    assert set(json.loads(bench.CONTEXTS_PATH.read_text(encoding="utf-8"))) == {"Q1", "Q2"}


def test_load_contexts_refuses_an_empty_retrieval_and_caches_nothing(monkeypatch, bench):
    monkeypatch.setattr(bench, "retrieve", lambda state: {"retrieved_chunks": []})
    with pytest.raises(bench.BackendUnavailable, match="no passage"):
        bench.load_contexts([_item()], refresh=False)
    assert not bench.CONTEXTS_PATH.exists()


def test_run_once_records_the_answer_sources_and_structured_failure(monkeypatch, bench):
    result = {"response": _response("Validation en 48 heures ouvrées.", ["guide.docx"]), "timing": {"llm_call_count": 2},
              "sources_fallback_eligible": True}
    monkeypatch.setattr(bench, "generate", lambda state: result)
    record = bench.run_once(_item(), [{"document": "d"}])
    assert (record["error"], record["fact_recall"], record["source_recall"]) == (None, 1.0, 1.0)
    assert (record["cited_sources"], record["llm_calls"], record["structured_failed"]) == (["guide.docx"], 2, True)
    assert (record["confidence"], record["answer_chars"]) == (0.9, len("Validation en 48 heures ouvrées."))


def test_run_once_flags_the_fallback_answer_of_generate_as_an_error(monkeypatch, bench):
    failure = {"response": _response(bench.GENERATION_ERROR_PREFIX + "e. Détails: timeout"), "timing": {}}
    monkeypatch.setattr(bench, "generate", lambda state: failure)
    assert bench.run_once(_item(), [{"document": "d"}])["error"].startswith(bench.GENERATION_ERROR_PREFIX)


def test_run_once_flags_an_exception_as_an_error(monkeypatch, bench):
    def boom(state):
        raise RuntimeError("down")

    monkeypatch.setattr(bench, "generate", boom)
    assert bench.run_once(_item(), [{"document": "d"}])["error"] == "RuntimeError: down"


def _run_execute(monkeypatch, bench, failures, count=5):
    outcomes = iter(failures)
    monkeypatch.setattr(bench, "run_once", lambda item, chunks: {"error": "x" if next(outcomes) else None, "seconds": 1.0,
                                                                  "fact_recall": 1.0, "source_recall": 1.0, "abstained": False})
    todo = [(_item(id=f"Q{number}"), 1) for number in range(count)]
    runs = {}
    chunks = {item["id"]: [] for item, _ in todo}
    return bench.execute(todo, runs, "m1", {"vram_fraction": 1.0}, chunks), runs


def test_execute_stops_after_three_consecutive_errors(monkeypatch, bench):
    finished, runs = _run_execute(monkeypatch, bench, [True] * 5)
    assert finished is False
    assert len(runs) == bench_common.MAX_CONSECUTIVE_ERRORS


def test_execute_resets_the_error_counter_after_a_success(monkeypatch, bench):
    finished, runs = _run_execute(monkeypatch, bench, [True, True, False, True, True])
    assert finished is True
    assert len(runs) == 5


def test_resume_skips_done_runs_and_retries_errors_on_request(bench):
    runs = {("m1", "Q1", 1): _record(question_id="Q1"), ("m1", "Q2", 1): _record(question_id="Q2", error="x")}
    questions = [_item(id="Q1"), _item(id="Q2"), _item(id="Q3")]
    pending = lambda retry: [item["id"] for item, _ in bench.run_store.pending_runs("m1", questions, 1, runs, lambda previous: retry and bool(previous["error"]))]
    assert pending(False) == ["Q3"]
    assert pending(True) == ["Q2", "Q3"]


def test_model_stats_exclude_errors_and_split_answerable_from_unanswerable(bench):
    records = [
        _record(fact_recall=1.0), _record(question_id="Q2", fact_recall=0.5, source_recall=0.5),
        _record(question_id="Q3", error="x", fact_recall=0.0),
        _record(question_id="T1", answerable=False, fact_recall=None, source_recall=None, abstained=True),
        _record(question_id="T2", answerable=False, fact_recall=None, source_recall=None, abstained=False),
    ]
    stats = bench.model_stats(records)
    assert (stats["runs"], stats["errors"]) == (5, 1)
    assert (stats["facts"], stats["complete"], stats["sources"], stats["abstained"]) == (0.75, 0.5, 0.75, 0.5)


def test_model_stats_without_a_valid_run_has_no_division_by_zero(bench):
    stats = bench.model_stats([_record(error="x")])
    assert (stats["facts"], stats["abstained"], stats["p50"], stats["p90"]) == (None, None, None, None)


def test_model_stats_percentiles_and_minimum_vram(bench):
    records = [_record(question_id=f"Q{number}", seconds=float(number), vram_fraction=1.0 if number else 0.8) for number in range(1, 11)]
    stats = bench.model_stats(records)
    assert (stats["p50"], stats["p90"], stats["vram"], stats["confidence"], stats["answer_chars"]) == (5.5, 9.0, 1.0, 0.9, 40)


def test_report_prints_models_and_questions(capsys, bench):
    runs = {("m1", "Q1", 1): _record(), ("m2", "Q1", 1): _record(model="m2", error="x")}
    bench.print_report(runs)
    output = capsys.readouterr().out
    assert "m1" in output and "m2" in output and "Q1" in output
