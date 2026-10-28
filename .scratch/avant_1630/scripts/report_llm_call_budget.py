#!/usr/bin/env python3

import argparse
import statistics
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from core.guardrails import REACT_RECURSION_LIMIT
from core.session.reasoning_trace_logger import ReasoningTraceLogger, MAX_HOPS_PER_QUESTION


BRANCH_ORDER = ["documentaire", "donnees_erp"]
BRANCH_LABELS = {
    "documentaire": "RAG simple (documentaire)",
    "donnees_erp": "Function Calling (donnees_erp)",
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
        "# Rapport - Budget LLM par branche\n",
        f"**Source :** `{logger.log_filepath}`\n",
        f"**Nombre total de questions tracees :** {len(summaries)}\n",
        "---\n",
    ]

    if not summaries:
        lines.append(
            "Aucune trace enregistree pour le moment -- ce rapport se remplit au fil des "
            "questions reellement posees (documentaire / donnees_erp "
            "logguent chacune une SUMMARY dans `reasoning_trace.jsonl` a chaque appel). "
            "Lancer `scripts/run_adversarial_benchmark.py` ou interroger le pipeline via "
            "`rag.graph.query_graph()` pour peupler ce rapport avec des chiffres reels.\n"
        )
        return "\n".join(lines)

    by_branch = {}
    for s in summaries:
        by_branch.setdefault(s.get("branch", "unknown"), []).append(s)

    lines.append("## Comparaison par branche\n")
    lines.append("| Branche | N questions | Appels LLM (moy/med/max) | Hops (moy/med/max) | Plafond de sauts atteint |")
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
            f"| {branch} (branche non repertoriee) | {llm_s['n']} "
            f"| {llm_s['mean']} / {llm_s['median']} / {llm_s['max']} "
            f"| {hop_s['mean']} / {hop_s['median']} / {hop_s['max']} "
            f"| {cap_hits}/{len(recs)} |"
        )

    lines.append(
        f"\n*Plafond de sauts par question : `donnees_erp` applique "
        f"`REACT_RECURSION_LIMIT={REACT_RECURSION_LIMIT}`, `documentaire` ne fait jamais de hop (0 par construction). "
        f"Valeur generique de reference : `MAX_HOPS_PER_QUESTION={MAX_HOPS_PER_QUESTION}` "
        f"(core.session.reasoning_trace_logger).*\n"
    )

    lines.append("---\n## Lecture\n")
    lines.append(
        "- `documentaire` (RAG simple) sert de plancher de comparaison : 0 hop, 1-2 appels LLM "
        "(1 en generation structuree, +1 seulement si le fallback texte-brut est declenche).\n"
        f"- `donnees_erp` (Function Calling) fait jusqu'a `REACT_RECURSION_LIMIT` ({REACT_RECURSION_LIMIT}) allers-retours "
        "outil+LLM, plus 1 appel de synthese forcee si la limite est atteinte sans reponse finale.\n"
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
    parser = argparse.ArgumentParser(description=" / J48 LLM call budget report.")
    parser.add_argument("--trace-id", help="Print the full reasoning path for one trace_id instead of the aggregate report.")
    parser.add_argument("--log-file", help="Override the reasoning_trace.jsonl path.")
    args = parser.parse_args()

    log_filepath = Path(args.log_file) if args.log_file else None

    if args.trace_id:
        print_trace(args.trace_id, log_filepath=log_filepath)
        return

    report = build_budget_report(log_filepath=log_filepath)
    print(report)

    root_dir = Path(__file__).resolve().parent.parent
    todo_dir = root_dir / "todo"
    todo_dir.mkdir(exist_ok=True)
    out_path = todo_dir / ".md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nSaved report to: {out_path}")


if __name__ == "__main__":
    main()
