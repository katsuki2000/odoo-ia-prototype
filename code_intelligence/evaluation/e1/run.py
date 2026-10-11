"""CLI: run E1 systems R0/R1 offline on the calibration seed (no LLM)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .cases import load_calibration_cases
from .config import load_e1_config
from .metrics import score_resolution_case, summarize_system_scores
from .systems import run_system


def _load_graph():
    from code_intelligence.graph.loader import get_code_intelligence_graph

    return get_code_intelligence_graph()


def run_offline(
    systems: list[str],
    *,
    graph=None,
    skip_if_no_graph: bool = True,
) -> dict:
    config = load_e1_config()
    cases, cases_digest, meta = load_calibration_cases()
    primary_k = int(config.get("primary_k", 5))

    if graph is None:
        try:
            graph = _load_graph()
        except Exception as exc:
            if skip_if_no_graph:
                return {
                    "status": "skipped",
                    "reason": f"graph unavailable: {exc}",
                    "config_digest": config.get("_digest"),
                    "cases_digest": cases_digest,
                }
            raise

    report = {
        "status": "ok",
        "config_digest": config["_digest"],
        "cases_digest": cases_digest,
        "cases_meta": meta,
        "systems": {},
    }
    for system_id in systems:
        scores = []
        for case in cases:
            try:
                output = run_system(
                    system_id, case, graph, language=case.language, config=config
                )
            except NotImplementedError as exc:
                report["systems"][system_id] = {"status": "not_implemented", "detail": str(exc)}
                break
            scores.append(
                score_resolution_case(
                    case,
                    candidates=output.candidates,
                    declared_ambiguous=output.declared_ambiguous,
                    is_resolved=output.is_resolved,
                    primary_k=primary_k,
                )
            )
        else:
            report["systems"][system_id] = {
                "status": "scored",
                "summary": summarize_system_scores(scores, primary_k=primary_k),
                "scores": scores,
            }
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run E1 offline resolution comparison (R0/R1).")
    parser.add_argument(
        "--systems",
        default="R0,R1,R2",
        help="Comma-separated system ids (default: R0,R1,R2). R4-R5 not implemented yet.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args(argv)
    systems = [item.strip() for item in args.systems.split(",") if item.strip()]
    report = run_offline(systems)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("status") in {"ok", "skipped"} else 1
    print(f"status={report.get('status')} config={report.get('config_digest', '')[:12]}…")
    if report.get("status") == "skipped":
        print(report.get("reason"))
        return 0
    for system_id, block in report.get("systems", {}).items():
        if block.get("status") != "scored":
            print(f"{system_id}: {block.get('status')} — {block.get('detail', '')}")
            continue
        summary = block["summary"]
        print(
            f"{system_id}: n={summary['n']} "
            f"recall@5={summary.get('recall_at_5')} "
            f"silent_false={summary.get('silent_false_rate')} "
            f"clarify={summary.get('clarify_correct_rate')}"
        )
        for family, stats in summary.get("by_family", {}).items():
            print(
                f"  {family}: n={stats['n']} recall@5={stats.get('recall_at_5')} "
                f"silent_false={stats.get('silent_false_rate')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
