#!/usr/bin/env python3
"""Run the production concept resolver (with its LLM arbitration) on a calibration case file."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.evaluation.e1.cases import DATA_DIR, load_calibration_cases
from code_intelligence.evaluation.resolver_calibration import score_case, summarize
from code_intelligence.graph.loader import get_code_intelligence_graph

DEFAULT_CASES = DATA_DIR / "role_calibration_cases.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="+", default=[], help="case ids to run")
    args = parser.parse_args()

    from core.llm.llm_client import get_chat_llm

    cases, digest, meta = load_calibration_cases(args.cases)
    if args.only:
        cases = tuple(case for case in cases if case.case_id in args.only)
    graph = get_code_intelligence_graph(translation_languages=None, request_language=None)
    llm = get_chat_llm(temperature=0.0, max_retries=0)

    rows = []
    for case in cases:
        started = time.perf_counter()
        concept = resolve_business_term(case.question, graph, llm=llm, language=case.language)
        row = score_case(case, concept)
        row["latency_s"] = round(time.perf_counter() - started, 1)
        rows.append(row)
        print(f"{case.case_id:40s} {row['verdict']:18s} chosen={row['chosen']} step={row['source_step']} "
              f"raw={row['arbitration_raw']} ({row['latency_s']}s)", flush=True)

    report = {"cases_digest": digest, "cases_path": str(args.cases), "summary": summarize(rows), "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
