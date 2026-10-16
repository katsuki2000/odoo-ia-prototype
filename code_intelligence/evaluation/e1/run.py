"""CLI: run E1 systems R1 and following offline on the calibration seed."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from .cases import load_calibration_cases
from .config import load_e1_config
from .metrics import score_resolution_case, summarize_system_scores
from .projection import ModelProjector
from .systems import run_system


def load_graph(languages=()):
    """Active graph with the translations of every case language.

    Without translation_languages the graph only carries source (en_US) labels, so French
    questions would be compared to English labels only and R1 to R4 would be meaningless.
    """
    from code_intelligence.graph.loader import get_code_intelligence_graph

    if languages:
        return get_code_intelligence_graph(translation_languages=list(languages))
    return get_code_intelligence_graph()


DEFAULT_REPORT_PATH = Path(__file__).resolve().parents[3] / "captures" / "e1_report.json"


def persist_report(report: dict, output_path: Optional[Path]) -> None:
    """Atomic write, so a crash while writing never leaves a truncated report."""
    if output_path is None:
        return
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=output_path.parent, suffix=".tmp", delete=False, encoding="utf-8",
    ) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, output_path)


def run_offline(
    systems: list[str],
    *,
    graph=None,
    skip_if_no_graph: bool = True,
    output_path: Optional[Path] = None,
    on_system_done: Optional[Callable[[str, dict], None]] = None,
    llm=None,
) -> dict:
    config = load_e1_config()
    cases, cases_digest, meta = load_calibration_cases()
    primary_k = int(config.get("primary_k", 5))

    if graph is None:
        try:
            graph = load_graph(sorted({case.language for case in cases if case.language}))
        except Exception as exc:
            if skip_if_no_graph:
                return {
                    "status": "skipped",
                    "reason": f"graph unavailable: {exc}",
                    "config_digest": config.get("_digest"),
                    "cases_digest": cases_digest,
                }
            raise

    projector = ModelProjector(graph)
    report = {
        "status": "in_progress",
        "config_digest": config["_digest"],
        "cases_digest": cases_digest,
        "cases_meta": meta,
        "systems": {},
    }
    for system_id in systems:
        scores = []
        try:
            for case in cases:
                try:
                    output = run_system(
                        system_id, case, graph, language=case.language, config=config, llm=llm,
                    )
                except NotImplementedError as exc:
                    report["systems"][system_id] = {"status": "not_implemented", "detail": str(exc)}
                    break
                row = score_resolution_case(
                    case,
                    candidates=output.candidates,
                    declared_ambiguous=output.declared_ambiguous,
                    is_resolved=output.is_resolved,
                    primary_k=primary_k,
                    projector=projector,
                )
                row["diagnostics"] = output.diagnostics
                scores.append(row)
            else:
                report["systems"][system_id] = {
                    "status": "scored",
                    "summary": summarize_system_scores(scores, primary_k=primary_k),
                    "scores": scores,
                }
        except Exception as exc:  # one failing system (e.g. embedding tunnel) must not erase the others
            report["systems"][system_id] = {
                "status": "error",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        persist_report(report, output_path)
        if on_system_done is not None:
            on_system_done(system_id, report["systems"][system_id])
    failed = any(block.get("status") == "error" for block in report["systems"].values())
    report["status"] = "partial" if failed else "ok"
    persist_report(report, output_path)
    return report


def print_system_summary(system_id: str, block: dict) -> None:
    if block.get("status") != "scored":
        print(f"{system_id}: {block.get('status')} — {block.get('detail', '')}", flush=True)
        return
    summary = block["summary"]
    print(
        f"{system_id}: n={summary['n']} "
        f"recall@5={summary.get('recall_at_5')} (raw {summary.get('recall_at_5_raw')}) "
        f"silent_false={summary.get('silent_false_rate')} (raw {summary.get('silent_false_rate_raw')}) "
        f"clarify={summary.get('clarify_correct_rate')}",
        flush=True,
    )
    for family, stats in summary.get("by_family", {}).items():
        print(
            f"  {family}: n={stats['n']} recall@5={stats.get('recall_at_5')} "
            f"(raw {stats.get('recall_at_5_raw')}) silent_false={stats.get('silent_false_rate')}",
            flush=True,
        )


def _enable_progress_logging() -> None:
    """Show E1 progress (dense index batches) on stderr without enabling other loggers."""
    e1_logger = logging.getLogger("code_intelligence.evaluation.e1")
    if not e1_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        e1_logger.addHandler(handler)
    e1_logger.setLevel(logging.INFO)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run E1 offline resolution comparison.")
    parser.add_argument(
        "--systems",
        default="R1,R2",
        help="Comma-separated system ids (default: R1,R2). R3, R4 and R6 call the embedding backend, R6 also the LLM; R5 not implemented yet.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="JSON report, rewritten after each system (default: captures/e1_report.json).",
    )
    args = parser.parse_args(argv)
    _enable_progress_logging()
    systems = [item.strip() for item in args.systems.split(",") if item.strip()]
    printer = None if args.json else print_system_summary
    llm = None
    if "R6" in systems:
        from .llm import resolve_e1_llm_callable

        llm = resolve_e1_llm_callable()
    report = run_offline(systems, output_path=args.output, on_system_done=printer, llm=llm)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("status") in {"ok", "skipped"} else 1
    print(f"status={report.get('status')} config={str(report.get('config_digest', ''))[:12]}… report={args.output}")
    if report.get("status") == "skipped":
        print(report.get("reason"))
        return 0
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
