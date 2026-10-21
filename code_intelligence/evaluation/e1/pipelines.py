"""Comparison of eight resolution pipelines (A-H) on labelled cases. Harness only: never imported by the agent loop.

A = RapidFuzz; B = RRF(RapidFuzz, BGE); C = B + reranker; D = B + closed-list LLM arbitration;
E = RRF(RapidFuzz, BGE, BM25) + reranker + closed-list LLM arbitration;
F = RRF(RapidFuzz, BM25); G = B + BM25; H = G + reranker (see SPEC).
Components are injected, so the composition and the scoring are testable without any backend.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .arbitration import ArbitrationStatus
from .fusion import reciprocal_rank_fusion

PIPELINES = ("A", "B", "C", "D", "E", "F", "G", "H")
ARBITRATED = frozenset({"D", "E"})
LABELS = {
    "A": "RapidFuzz",
    "B": "RapidFuzz + BGE",
    "C": "RapidFuzz + BGE + reranker",
    "D": "RapidFuzz + BGE + arbitrage LLM",
    "E": "RapidFuzz + BGE + BM25 + reranker + arbitrage LLM",
    "F": "RapidFuzz + BM25",
    "G": "RapidFuzz + BGE + BM25",
    "H": "RapidFuzz + BGE + BM25 + reranker",
}
# pipeline -> (retrieval sources fused by RRF, rerank the head, closed-list LLM arbitration)
SPEC = {
    "A": (("fuzzy",), False, False),
    "B": (("fuzzy", "dense"), False, False),
    "C": (("fuzzy", "dense"), True, False),
    "D": (("fuzzy", "dense"), False, True),
    "E": (("fuzzy", "dense", "bm25"), True, True),
    "F": (("fuzzy", "bm25"), False, False),
    "G": (("fuzzy", "dense", "bm25"), False, False),
    "H": (("fuzzy", "dense", "bm25"), True, False),
}
RECALL_KS = (1, 5, 10)


@dataclass(frozen=True)
class Case:
    case_id: str
    question: str
    language: str
    expected: tuple[str, ...]  # "model:x" references
    rule: str = "none"  # "none" or "must_clarify"
    family: str = ""

    @property
    def scored(self) -> bool:
        """Decision metrics only exist for answerable cases whose every expected object is a model."""
        return self.rule == "none" and bool(self.expected) and all(r.startswith("model:") for r in self.expected)


@dataclass
class Components:
    """Each stage maps (question, language) to a ranked list of ``model:`` references."""

    fuzzy: Callable[[str, str], list[str]]
    dense: Callable[[str, str], list[str]]
    bm25: Callable[[str, str], list[str]]
    rerank: Callable[[str, str, Sequence[str]], list[str]]
    arbitrate: Callable[[str, str, Sequence[str]], Any]  # -> ArbitrationResult-like (status, choice, raw)


@dataclass
class Output:
    candidates: tuple[str, ...]
    status: Optional[str] = None
    chosen: Optional[str] = None
    shortlist: tuple[str, ...] = ()
    ms: float = 0.0
    llm_calls: int = 0
    raw: str = ""


@dataclass
class _Trace:
    """Stage results are computed once per question; each pipeline is charged the stage times it uses."""

    comp: Components
    case: Case
    cache: dict = field(default_factory=dict)
    ms: float = 0.0

    def get(self, stage: str, *extra):
        key = (stage, tuple(extra))
        if key not in self.cache:
            fn = getattr(self.comp, stage)
            started = time.monotonic()
            value = fn(self.case.question, self.case.language, *extra)
            self.cache[key] = (value, (time.monotonic() - started) * 1000)
        value, elapsed = self.cache[key]
        self.ms += elapsed
        return value


def fuse(rankings: Mapping[str, Sequence[str]], constant: int = 60) -> list[str]:
    return [ref for ref, _ in reciprocal_rank_fusion(rankings, constant=constant)]


def run_pipeline(
    pipeline: str, trace: _Trace, *, top_k: int = 5, rerank_depth: int = 20, rrf_constant: int = 60,
) -> Output:
    trace.ms = 0.0
    sources, rerank, arbitrate = SPEC[pipeline]
    rankings = {name: trace.get(name) for name in sources}
    fused = list(rankings[sources[0]]) if len(sources) == 1 else fuse(rankings, rrf_constant)
    if rerank:
        head = fused[:rerank_depth]
        fused = list(trace.get("rerank", tuple(head))) + fused[rerank_depth:]
    if not arbitrate:
        return Output(tuple(fused), ms=trace.ms)
    shortlist = tuple(fused[:top_k])
    if not shortlist:
        return Output((), status="NO_CANDIDATES", ms=trace.ms)
    result = trace.get("arbitrate", shortlist)
    chosen = result.choice if result.status is ArbitrationStatus.CHOSEN else None
    rest = tuple(ref for ref in shortlist if ref != chosen)
    return Output(
        ((chosen, *rest) if chosen else shortlist), status=result.status.value, chosen=chosen,
        shortlist=shortlist, ms=trace.ms, llm_calls=1, raw=str(getattr(result, "raw", ""))[:200],
    )


def score_row(case: Case, out: Output) -> dict[str, Any]:
    expected = set(case.expected)
    ranked = list(out.candidates)
    first = next((i + 1 for i, ref in enumerate(ranked) if ref in expected), None)
    row: dict[str, Any] = {
        "case_id": case.case_id, "family": case.family, "rule": case.rule, "scored": case.scored,
        "expected": list(case.expected), "candidates": ranked[:10], "status": out.status,
        "chosen": out.chosen, "shortlist": list(out.shortlist), "ms": round(out.ms, 1),
        "llm_calls": out.llm_calls, "first_expected_rank": first,
        "reciprocal_rank": (1 / first) if first else 0.0,
    }
    for k in RECALL_KS:
        row[f"recall_at_{k}"] = bool(expected) and expected <= set(ranked[:k])
    row["shortlist_recall"] = bool(expected) and expected <= set(out.shortlist)
    chosen = out.status == ArbitrationStatus.CHOSEN.value
    row["correct_decision"] = chosen and out.chosen in expected
    row["silent_false"] = chosen and out.chosen not in expected
    row["abstained"] = out.status is not None and not chosen
    return row


def _frac(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    k = sum(bool(r.get(key)) for r in rows)
    return {"k": k, "n": len(rows), "rate": round(k / len(rows), 3) if rows else None}


def summarize(pipeline: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r["scored"]]
    summary: dict[str, Any] = {
        "n_cases": len(rows), "n_scored": len(scored),
        **{f"recall_at_{k}": _frac(scored, f"recall_at_{k}") for k in RECALL_KS},
        "mrr": round(sum(r["reciprocal_rank"] for r in scored) / len(scored), 3) if scored else None,
        "ms_mean": round(sum(r["ms"] for r in rows) / len(rows), 1) if rows else None,
    }
    if pipeline in ARBITRATED:
        clarify = [r for r in rows if r["rule"] == "must_clarify"]
        summary.update(
            correct_decision=_frac(scored, "correct_decision"),
            silent_false=_frac(scored, "silent_false"),
            abstained=_frac(scored, "abstained"),
            shortlist_recall=_frac(scored, "shortlist_recall"),
            strict_clarification={
                "k": sum(r["status"] != ArbitrationStatus.CHOSEN.value for r in clarify), "n": len(clarify),
            },
            llm_calls=sum(r["llm_calls"] for r in rows),
        )
    return summary


def cell(pipeline: str, row: Mapping[str, Any]) -> str:
    """One compact verdict per case and pipeline, for the case-by-case matrix."""
    if row.get("error"):
        return "ERR"
    if not row["scored"]:
        return "abst" if row["abstained"] else ("choisi" if pipeline in ARBITRATED else "n/a")
    if pipeline in ARBITRATED:
        return "OK" if row["correct_decision"] else ("FAUX" if row["silent_false"] else "abst")
    rank = row["first_expected_rank"]
    return f"r{rank}" if rank else "r-"


def run_comparison(
    cases: Sequence[Case],
    comp: Components,
    pipelines: Sequence[str] = PIPELINES,
    *,
    top_k: int = 5,
    rerank_depth: int = 20,
    max_consecutive_errors: int = 3,
    persist: Optional[Callable[[dict], None]] = None,
    on_done: Optional[Callable[[str, dict], None]] = None,
) -> dict[str, Any]:
    traces = {case.case_id: _Trace(comp, case) for case in cases}
    report: dict[str, Any] = {"status": "in_progress", "pipelines": {}, "cases": [c.case_id for c in cases]}
    for pipeline in pipelines:
        rows: list[dict[str, Any]] = []
        consecutive = 0
        for case in cases:
            try:
                out = run_pipeline(pipeline, traces[case.case_id], top_k=top_k, rerank_depth=rerank_depth)
                rows.append(score_row(case, out))
                consecutive = 0
            except Exception as exc:  # a backend failure is a measured outcome, never a silent skip
                consecutive += 1
                rows.append({**score_row(case, Output(())), "error": f"{type(exc).__name__}: {exc}"[:300]})
                if consecutive >= max_consecutive_errors:
                    break
        errors = [r for r in rows if r.get("error")]
        ok_rows = [r for r in rows if not r.get("error")]
        status = "error" if len(errors) == len(rows) else ("partial" if errors or len(rows) < len(cases) else "scored")
        report["pipelines"][pipeline] = {
            "label": LABELS[pipeline], "status": status, "summary": summarize(pipeline, ok_rows),
            "rows": rows, "detail": errors[0]["error"] if errors else "",
        }
        if persist:
            persist(report)
        if on_done:
            on_done(pipeline, report["pipelines"][pipeline])
    report["status"] = "ok" if all(b["status"] == "scored" for b in report["pipelines"].values()) else "partial"
    if persist:
        persist(report)
    return report
