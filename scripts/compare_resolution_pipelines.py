"""Compare eight resolution pipelines on labelled cases (exploratory; not the pre-registered E1 decision D1).

A = RapidFuzz | B = RapidFuzz+BGE | C = B+reranker | D = B+LLM arbitration | E = RapidFuzz+BGE+BM25+reranker+LLM arbitration
F = RapidFuzz+BM25 | G = B+BM25 | H = G+reranker

Read-only on MIRO behaviour. A and F need no server (RapidFuzz, BM25); B, C, D, E, G, H need the embedding tunnel (BGE),
C, E and H a cross-encoder model, D and E the arbitration LLM of the project's .env.

    python scripts/compare_resolution_pipelines.py --pipelines A,F          # offline, seconds
    python scripts/compare_resolution_pipelines.py --dense e1               # everything
    python scripts/compare_resolution_pipelines.py --dense production --pipelines B,D
    python scripts/compare_resolution_pipelines.py --reranker-model BAAI/bge-reranker-v2-m3 --pipelines C,E,H
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from code_intelligence.evaluation.e1.cases import load_calibration_cases  # noqa: E402
from code_intelligence.evaluation.e1.pipeline_components import (  # noqa: E402
    DEFAULT_RERANKER, DENSE_VARIANTS, build_components,
)
from code_intelligence.evaluation.e1.pipelines import (  # noqa: E402
    ARBITRATED, LABELS, PIPELINES, Case, cell, run_comparison,
)
from code_intelligence.evaluation.e1.run import load_graph, persist_report  # noqa: E402

DATA = ROOT / "code_intelligence" / "evaluation" / "e1" / "data"
CASE_FILES = ("calibration_cases.json", "role_calibration_cases.json", "role_calibration_cases_ext.json")
BANKS = ("tests/native_n1_question_bank.json", "tests/custom_b9_question_bank.json")
DEFAULT_OUTPUT = ROOT / "captures" / "pipeline_comparison.json"
BANNER = (
    "EXPLORATOIRE : cas d'etalonnage E1 (jamais le held_out), effectifs faibles ; ne remplace pas la decision D1. "
    "Les pipelines C, E et H dependent du modele de reranker choisi."
)


def load_cases(expected_path: Path | None) -> list[Case]:
    cases: dict[str, Case] = {}
    for name in CASE_FILES:
        loaded, _digest, _meta = load_calibration_cases(DATA / name)
        for c in loaded:
            cases[c.case_id] = Case(c.case_id, c.question, c.language, tuple(c.expected_objects),
                                    c.abstention_rule, c.family)
    if expected_path:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        for bank in BANKS:
            data = json.loads((ROOT / bank).read_text(encoding="utf-8"))
            for item in data["questions"] if isinstance(data, dict) else data:
                models = expected.get(item["id"])
                if models:
                    question = item.get("business_question") or item["question"]
                    refs = tuple(m if m.startswith("model:") else f"model:{m}" for m in models)
                    cases[item["id"]] = Case(item["id"], question, "fr", refs, "none", "bank")
    return [cases[key] for key in sorted(cases)]


def _rate(block: dict | None) -> str:
    if not block or block.get("rate") is None:
        return "n/a"
    return f"{block['k']}/{block['n']} ({block['rate']:.0%})"


def print_summary(pipeline: str, block: dict) -> None:
    s = block["summary"]
    print(f"\n{pipeline} {block['label']} : {block['status']} {block['detail']}", flush=True)
    if block["status"] == "error":
        return
    print(f"  cas notes {s['n_scored']}/{s['n_cases']} | recall@1 {_rate(s['recall_at_1'])} | "
          f"@5 {_rate(s['recall_at_5'])} | @10 {_rate(s['recall_at_10'])} | MRR {s['mrr']} | {s['ms_mean']} ms/cas")
    if pipeline in ARBITRATED:
        clar = s["strict_clarification"]
        print(f"  decision correcte {_rate(s['correct_decision'])} | faux silencieux {_rate(s['silent_false'])} | "
              f"abstention {_rate(s['abstained'])} | liste de 5 contient l'attendu {_rate(s['shortlist_recall'])} | "
              f"clarification stricte {clar['k']}/{clar['n']} | appels LLM {s['llm_calls']}")


def print_matrix(report: dict) -> None:
    ids = list(report["pipelines"])
    print("\nCas par cas (A-C : rang de l'attendu ; D-E : OK / FAUX / abst) :")
    print(f"  {'cas':<46}" + "".join(f"{p:>8}" for p in ids))
    for i, case_id in enumerate(report["cases"]):
        cells = []
        for p in ids:
            rows = report["pipelines"][p]["rows"]
            cells.append(cell(p, rows[i]) if i < len(rows) else "-")
        print(f"  {case_id[:45]:<46}" + "".join(f"{c:>8}" for c in cells))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pipelines", default=",".join(PIPELINES), help="Comma-separated subset of A,B,C,D,E,F,G,H.")
    parser.add_argument("--dense", choices=DENSE_VARIANTS, default="e1", help="BGE cards: E1 (7 node types) or production.")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER)
    parser.add_argument("--expected", type=Path, help='JSON {"PUR-Q1": ["purchase.order"], ...} to score the question banks.')
    parser.add_argument("--limit", type=int, help="Only the first N cases (smoke test).")
    parser.add_argument("--top-k", type=int, default=5, help="Closed-list size for the arbitration.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    chosen = [p.strip().upper() for p in args.pipelines.split(",") if p.strip()]
    unknown = [p for p in chosen if p not in PIPELINES]
    if unknown:
        parser.error(f"unknown pipeline(s): {unknown}")
    cases = load_cases(args.expected)[: args.limit]
    print(BANNER, f"\n{len(cases)} cas ; BGE={args.dense} ; reranker={args.reranker_model} ; PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED')}", flush=True)

    graph = load_graph(sorted({c.language for c in cases if c.language}))
    comp = build_components(graph, dense_variant=args.dense, reranker_model=args.reranker_model)

    def persist(report: dict) -> None:
        persist_report({"banner": BANNER, "dense": args.dense, "reranker": args.reranker_model,
                        "hash_seed": os.environ.get("PYTHONHASHSEED"), **report}, args.output)

    report = run_comparison(cases, comp, chosen, top_k=args.top_k, persist=persist, on_done=print_summary)
    print_matrix(report)
    print(f"\nstatus={report['status']} rapport={args.output}")
    for p in chosen:
        print(f"  {p} = {LABELS[p]}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    if "PYTHONHASHSEED" not in os.environ:
        # _fuzzy_match_graph breaks ties in set order, which depends on the hash seed
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, *sys.argv])
    sys.exit(main())
