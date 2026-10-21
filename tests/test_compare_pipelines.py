"""Pure tests of the A-E pipeline comparison: composition, scoring, failure handling (no backend)."""

from dataclasses import dataclass

import pytest

from code_intelligence.evaluation.e1.arbitration import ArbitrationStatus
from code_intelligence.evaluation.e1.pipelines import (
    ARBITRATED, PIPELINES, SPEC, Case, Components, Output, _Trace, cell, run_comparison, run_pipeline, score_row,
    summarize,
)


@dataclass
class _Result:
    status: ArbitrationStatus
    choice: str | None = None
    raw: str = ""


def _components(calls=None, *, arbitration=None, dense_error=None):
    calls = calls if calls is not None else []

    def stage(name, value):
        def run(question, language, *extra):
            calls.append(name)
            if name == "dense" and dense_error:
                raise dense_error
            return list(value)
        return run

    def rerank(question, language, refs):
        calls.append("rerank")
        return list(reversed(refs))

    def arbitrate(question, language, shortlist):
        calls.append("arbitrate")
        return arbitration or _Result(ArbitrationStatus.CHOSEN, shortlist[0])

    return Components(
        fuzzy=stage("fuzzy", ["model:a", "model:b"]),
        dense=stage("dense", ["model:b", "model:c"]),
        bm25=stage("bm25", ["model:c", "model:d"]),
        rerank=rerank,
        arbitrate=arbitrate,
    )


CASE = Case("c1", "q", "fr_FR", ("model:b",))


def test_only_answerable_model_cases_are_scored():
    assert CASE.scored
    assert not Case("c2", "q", "fr", ("menu:x",)).scored
    assert not Case("c3", "q", "fr", (), "must_clarify").scored
    assert not Case("c4", "q", "fr", ("model:b",), "must_clarify").scored


def test_a_is_rapidfuzz_alone_and_never_touches_other_stages():
    calls = []
    out = run_pipeline("A", _Trace(_components(calls), CASE))
    assert out.candidates == ("model:a", "model:b")
    assert calls == ["fuzzy"]


def test_b_fuses_rapidfuzz_and_bge_and_the_shared_item_wins():
    out = run_pipeline("B", _Trace(_components(), CASE))
    assert out.candidates[0] == "model:b"  # in both lists
    assert set(out.candidates) == {"model:a", "model:b", "model:c"}


def test_c_reranks_only_the_head_and_keeps_the_tail():
    trace = _Trace(_components(), CASE)
    out = run_pipeline("C", trace, rerank_depth=2)
    fused = run_pipeline("B", trace).candidates
    assert out.candidates == (fused[1], fused[0], fused[2])


def test_d_arbitrates_the_closed_list_and_puts_the_choice_first():
    arbitration = _Result(ArbitrationStatus.CHOSEN, "model:c")
    out = run_pipeline("D", _Trace(_components(arbitration=arbitration), CASE), top_k=3)
    assert out.chosen == "model:c" and out.candidates[0] == "model:c" and out.llm_calls == 1
    assert len(out.shortlist) == 3


def test_d_abstention_keeps_the_shortlist_and_chooses_nothing():
    out = run_pipeline("D", _Trace(_components(arbitration=_Result(ArbitrationStatus.NONE)), CASE))
    assert out.chosen is None and out.status == "NONE" and out.candidates == out.shortlist


def test_e_adds_bm25_and_the_reranker_before_arbitration():
    calls = []
    run_pipeline("E", _Trace(_components(calls), CASE))
    assert calls == ["fuzzy", "dense", "bm25", "rerank", "arbitrate"]


def test_stages_are_computed_once_per_question_across_pipelines():
    calls = []
    trace = _Trace(_components(calls), CASE)
    for pipeline in "ABCD":
        run_pipeline(pipeline, trace)
    assert calls.count("fuzzy") == 1 and calls.count("dense") == 1


def test_score_row_recall_mrr_and_decisions():
    row = score_row(CASE, Output(("model:a", "model:b"), status="CHOSEN", chosen="model:a", shortlist=("model:a", "model:b")))
    assert row["recall_at_1"] is False and row["recall_at_5"] is True
    assert row["first_expected_rank"] == 2 and row["reciprocal_rank"] == 0.5
    assert row["silent_false"] is True and row["correct_decision"] is False and row["abstained"] is False
    good = score_row(CASE, Output(("model:b",), status="CHOSEN", chosen="model:b", shortlist=("model:b",)))
    assert good["correct_decision"] is True and cell("D", good) == "OK"
    assert cell("D", row) == "FAUX" and cell("B", row) == "r2"


def test_summary_counts_strict_clarification_on_must_clarify_cases_only():
    clarify = Case("c5", "q", "fr", (), "must_clarify")
    rows = [
        score_row(CASE, Output(("model:b",), status="CHOSEN", chosen="model:b", shortlist=("model:b",))),
        score_row(clarify, Output(("model:a", "model:b"), status="AMBIGUOUS", shortlist=("model:a", "model:b"))),
    ]
    summary = summarize("D", rows)
    assert summary["n_scored"] == 1 and summary["correct_decision"]["k"] == 1
    assert summary["strict_clarification"] == {"k": 1, "n": 1}


def test_a_failing_backend_stops_that_pipeline_but_not_the_others():
    cases = [Case(f"c{i}", "q", "fr", ("model:b",)) for i in range(6)]
    comp = _components(dense_error=ConnectionError("tunnel offline"))
    report = run_comparison(cases, comp, ["A", "B"], max_consecutive_errors=3)
    assert report["pipelines"]["A"]["status"] == "scored"
    assert report["pipelines"]["B"]["status"] == "error"
    assert len(report["pipelines"]["B"]["rows"]) == 3  # stopped after 3 consecutive errors
    assert "tunnel offline" in report["pipelines"]["B"]["detail"]
    assert report["status"] == "partial"


def test_report_is_persisted_after_each_pipeline():
    snapshots = []
    run_comparison([CASE], _components(), ["A", "B"], persist=lambda r: snapshots.append(set(r["pipelines"])))
    assert snapshots[0] == {"A"} and snapshots[1] == {"A", "B"}


def test_f_is_rapidfuzz_plus_bm25_and_runs_without_the_embedding_backend():
    calls = []
    out = run_pipeline("F", _Trace(_components(calls, dense_error=ConnectionError("offline")), CASE))
    assert calls == ["fuzzy", "bm25"]
    assert set(out.candidates) == {"model:a", "model:b", "model:c", "model:d"}


def test_g_is_b_plus_bm25_and_h_is_g_plus_the_reranker():
    trace = _Trace(_components(), CASE)
    b, g, h = (run_pipeline(p, trace, rerank_depth=3).candidates for p in "BGH")
    assert "model:d" not in b and "model:d" in g  # BM25 brings a candidate the others miss
    assert set(h) == set(g) and h[:3] == tuple(reversed(g[:3]))


def test_the_ladder_g_h_e_changes_one_component_at_a_time():
    spec = {p: SPEC[p] for p in "GHE"}
    assert spec["G"][0] == spec["H"][0] == spec["E"][0] == ("fuzzy", "dense", "bm25")
    assert (spec["G"][1], spec["H"][1], spec["E"][1]) == (False, True, True)
    assert (spec["G"][2], spec["H"][2], spec["E"][2]) == (False, False, True)


def test_only_d_and_e_call_the_llm():
    calls = []
    trace = _Trace(_components(calls), CASE)
    for pipeline in PIPELINES:
        run_pipeline(pipeline, trace)
    assert calls.count("arbitrate") == 2  # one per arbitrated pipeline: their shortlists differ (E adds BM25)
    assert ARBITRATED == {"D", "E"}


@pytest.mark.parametrize("pipeline", list(PIPELINES))
def test_every_pipeline_runs_end_to_end_on_fake_components(pipeline):
    report = run_comparison([CASE], _components(), [pipeline])
    assert report["pipelines"][pipeline]["status"] == "scored"
