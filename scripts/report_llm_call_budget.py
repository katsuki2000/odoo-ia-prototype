#!/usr/bin/env python3

import argparse
import statistics
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config.settings import REACT_RECURSION_LIMIT
from core.session.reasoning_trace_logger import ReasoningTraceLogger


BRANCH_ORDER = ["documentation", "system"]
BRANCH_LABELS = {
    "documentation": "Simple RAG (documentation)",
    "system": "Function Calling (system)",
}


def _stats(values):
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "max": 0, "min": 0}
    return {
        "n": len(values),
        # statistics.mean() silently returns an int (not a float) when the
        # input is all-int and the result is a whole number (e.g. mean of
        # [1, 1] -> 1, not 1.0), while statistics.median() always returns a
        # float for even-length inputs (true division). Force float here so
        # mean/median render consistently ("1.0 / 1.0" not "1 / 1.0").
        "mean": round(float(statistics.mean(values)), 2),
        "median": round(float(statistics.median(values)), 2),
        "max": max(values),
        "min": min(values),
    }


def build_budget_report(log_filepath: Path = None) -> str:
    """Aggregate all SUMMARY records by branch and render a Markdown table
    comparing llm_call_count / hop_count across the two branches."""
    logger = ReasoningTraceLogger(log_filepath=log_filepath)
    summaries = logger.read_recent(limit=100000, record_type="SUMMARY")

    lines = [
        "# LLM call budget per branch\n",
        f"**Source:** `{logger.log_filepath}`\n",
        f"**Traced questions:** {len(summaries)}\n",
        "---\n",
    ]

    if not summaries:
        lines.append(
            "No trace recorded yet. The report fills up as questions are asked (the documentation and "
            "system branches each log one SUMMARY in `reasoning_trace.jsonl` per call). "
            "Query the pipeline through `core.graph.graph.query_graph()` to populate it.\n"
        )
        return "\n".join(lines)

    by_branch = {}
    for s in summaries:
        by_branch.setdefault(s.get("branch", "unknown"), []).append(s)

    lines.append("## Comparison by branch\n")
    lines.append("| Branch | Questions | LLM calls (mean/median/max) | Hops (mean/median/max) | Hop cap reached |")
    lines.append("|---|---|---|---|---|")

    for branch in BRANCH_ORDER:
        recs = by_branch.get(branch)
        if not recs:
            continue
        llm_counts = [r["llm_call_count"] for r in recs]
        hop_counts = [r["hop_count"] for r in recs]
        cap_hits = sum(1 for r in recs if r.get("hop_cap_hit"))
        llm_s = _stats(llm_counts)
        hop_s = _stats(hop_counts)
        lines.append(
            f"| {BRANCH_LABELS.get(branch, branch)} | {llm_s['n']} "
            f"| {llm_s['mean']} / {llm_s['median']} / {llm_s['max']} "
            f"| {hop_s['mean']} / {hop_s['median']} / {hop_s['max']} "
            f"| {cap_hits}/{len(recs)} ({round(100 * cap_hits / len(recs))}%) |"
        )

    # Any branch not in BRANCH_ORDER (unexpected label) still gets reported.
    for branch, recs in by_branch.items():
        if branch in BRANCH_ORDER:
            continue
        llm_counts = [r["llm_call_count"] for r in recs]
        hop_counts = [r["hop_count"] for r in recs]
        cap_hits = sum(1 for r in recs if r.get("hop_cap_hit"))
        llm_s = _stats(llm_counts)
        hop_s = _stats(hop_counts)
        lines.append(
            f"| {branch} (unlisted branch) | {llm_s['n']} "
            f"| {llm_s['mean']} / {llm_s['median']} / {llm_s['max']} "
            f"| {hop_s['mean']} / {hop_s['median']} / {hop_s['max']} "
            f"| {cap_hits}/{len(recs)} |"
        )

    lines.append(
        f"\n*Hop cap per question: `system` applies "
        f"`REACT_RECURSION_LIMIT={REACT_RECURSION_LIMIT}`, `documentation` never hops (0 by design).*\n"
    )

    lines.append("---\n## Reading\n")
    lines.append(
        "- `documentation` (simple RAG) is the comparison floor: 0 hops, 1-2 LLM calls "
        "(1 for structured generation, +1 only when the raw-text fallback triggers).\n"
        f"- `system` (function calling) makes up to `REACT_RECURSION_LIMIT` ({REACT_RECURSION_LIMIT}) tool+LLM round trips, "
        "plus 1 forced synthesis call when the limit is reached without a final answer.\n"
    )

    return "\n".join(lines)


def print_trace(trace_id: str, log_filepath: Path = None) -> None:
    """Print the full post-hoc reasoning path (all HOP records + the closing
    SUMMARY) for one specific trace_id, in call order."""
    logger = ReasoningTraceLogger(log_filepath=log_filepath)
    records = logger.read_trace(trace_id)
    if not records:
        print(f"No records found for trace_id={trace_id!r} in {logger.log_filepath}")
        return

    print(f"=== Reasoning path for trace_id={trace_id} ===")
    for rec in records:
        if rec.get("record_type") == "HOP":
            print(
                f"  [hop {rec['hop_index']}] {rec['tool_name']}({rec['tool_args']}) "
                f"-> {rec['elapsed_ms']}ms\n"
                f"      observation: {rec['observation_summary']}"
            )
        elif rec.get("record_type") == "SUMMARY":
            print(
                f"  [SUMMARY] branch={rec['branch']} hops={rec['hop_count']} "
                f"llm_calls={rec['llm_call_count']} total={rec['total_time_ms']}ms "
                f"hop_cap_hit={rec['hop_cap_hit']}"
            )


def main():
    parser = argparse.ArgumentParser(description="LLM call budget report.")
    parser.add_argument("--trace-id", help="Print the full reasoning path for one trace_id instead of the aggregate report.")
    parser.add_argument("--log-file", help="Override the reasoning_trace.jsonl path.")
    args = parser.parse_args()

    log_filepath = Path(args.log_file) if args.log_file else None

    if args.trace_id:
        print_trace(args.trace_id, log_filepath=log_filepath)
        return

    report = build_budget_report(log_filepath=log_filepath)
    print(report)

    out_path = project_root / "captures" / "llm_call_budget.md"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nSaved report to: {out_path}")


if __name__ == "__main__":
    main()
