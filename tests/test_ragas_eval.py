import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_ragas_eval.py"


@pytest.fixture
def ragas_script(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_ragas_eval_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _answer(model="qwen3:14b", question_id="FACT-01", pass_number=1, **fields):
    base = {"model": model, "question_id": question_id, "pass_number": pass_number,
            "answerable": True, "error": None, "answer": "Le 25 du mois."}
    return {**base, **fields}


def _score(model="qwen3:14b", question_id="FACT-01", pass_number=1, faithfulness=1.0, answer_relevancy=0.5, error=None):
    return {"model": model, "question_id": question_id, "pass_number": pass_number,
            "faithfulness": faithfulness, "answer_relevancy": answer_relevancy, "error": error}


def _runs(*records):
    return {(record["model"], record["question_id"], record["pass_number"]): record for record in records}


def test_only_answerable_answers_without_error_are_scored(ragas_script):
    runs = _runs(
        _answer(),
        _answer(question_id="TRAP-01", answerable=False),
        _answer(question_id="FACT-02", error="timeout"),
        _answer(question_id="FACT-03", answer="  "),
    )
    assert [record["question_id"] for record in ragas_script.scorable_answers(runs)] == ["FACT-01"]


def test_pending_answers_skip_scored_ones_and_retry_errors_on_demand(ragas_script):
    answers = [_answer(), _answer(question_id="FACT-02"), _answer(question_id="FACT-03")]
    results = _runs(_score(), _score(question_id="FACT-02", faithfulness=None, error="faithfulness: timeout"))
    assert [a["question_id"] for a in ragas_script.pending_answers(answers, results, False)] == ["FACT-03"]
    assert [a["question_id"] for a in ragas_script.pending_answers(answers, results, True)] == ["FACT-02", "FACT-03"]


def test_summary_averages_per_model_and_leaves_errors_out(ragas_script):
    results = _runs(
        _score(faithfulness=1.0, answer_relevancy=0.8),
        _score(question_id="FACT-02", faithfulness=0.5, answer_relevancy=0.6),
        _score(question_id="FACT-03", faithfulness=None, answer_relevancy=None, error="faithfulness: timeout"),
        _score(model="gemma4:26b", faithfulness=0.9, answer_relevancy=0.7),
    )
    summary = ragas_script.summarise(results)
    assert summary["qwen3:14b"] == (2, 0.75, pytest.approx(0.7))
    assert summary["gemma4:26b"] == (1, 0.9, 0.7)


def test_results_path_is_safe_for_any_model_name(ragas_script):
    assert ragas_script.results_path("hf.co/org/model:q4").name == "ragas_eval_hf.co_org_model_q4.jsonl"
