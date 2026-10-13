"""CLI: rescore a saved E1 report with the current metrics, without recomputing any retrieval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

from .cases import E1Case, load_calibration_cases
from .config import load_e1_config
from .metrics import score_resolution_case, summarize_system_scores
from .projection import ModelProjector
from .run import load_graph, persist_report, print_system_summary


def _rescored_row(row: dict, case: E1Case, projector, primary_k: int) -> dict:
    rescored = score_resolution_case(
        case,
        candidates=row["candidates"],
        declared_ambiguous=row["declared_ambiguous"],
        is_resolved=row["is_resolved"],
        primary_k=primary_k,
        projector=projector,
    )
    if "diagnostics" in row:
        rescored["diagnostics"] = row["diagnostics"]
    return rescored


def rescore_report(
    report: dict,
    cases: Sequence[E1Case],
    projector: Optional[Callable[[str], Sequence[str]]],
    *,
    cases_digest: str,
    primary_k: int = 5,
) -> dict:
    """Same report with every scored system re-evaluated from its stored candidates."""
    if report.get("cases_digest") != cases_digest:
        raise ValueError("the report was computed on a different calibration set; rescoring it would be meaningless")
    cases_by_id = {case.case_id: case for case in cases}
    systems = {}
    for system_id, block in report.get("systems", {}).items():
        if block.get("status") != "scored":
            systems[system_id] = block
            continue
        scores = [_rescored_row(row, cases_by_id[row["case_id"]], projector, primary_k) for row in block["scores"]]
        systems[system_id] = {
            **block,
            "summary": summarize_system_scores(scores, primary_k=primary_k),
            "scores": scores,
        }
    return {**report, "systems": systems, "rescored_with": "parent_model_projection"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Rescore a saved E1 report with model projection.")
    parser.add_argument("report", type=Path, help="Report written by e1.run (--output).")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Rescored report (default: <report>_rescored.json next to the input).",
    )
    args = parser.parse_args(argv)
    output_path = args.output or args.report.with_name(f"{args.report.stem}_rescored{args.report.suffix}")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    cases, cases_digest, _meta = load_calibration_cases()
    graph = load_graph(sorted({case.language for case in cases if case.language}))
    rescored = rescore_report(
        report,
        cases,
        ModelProjector(graph),
        cases_digest=cases_digest,
        primary_k=int(load_e1_config().get("primary_k", 5)),
    )
    persist_report(rescored, output_path)
    for system_id, block in rescored["systems"].items():
        print_system_summary(system_id, block)
    print(f"rescored report={output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
