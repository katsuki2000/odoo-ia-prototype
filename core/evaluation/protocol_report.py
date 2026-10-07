"""Render and write the evaluation protocol report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

METRIC_ORDER = (
    "cases",
    "accuracy_all_questions",
    "accuracy_all_questions_strict",
    "clarify_by_abstention_cases",
    "accuracy_answered_questions",
    "coverage",
    "unsupported_claim_rate",
    "answer_faithfulness",
    "wrong_tool_rate",
    "technical_identifier_leak_rate",
    "resolution_recall_at_k",
    "evidence_completeness",
    "claim_recall_documentary",
    "human_business_acceptance_rate",
    "human_rated_cases",
)
BREAKDOWNS = ("by_instance", "by_module", "by_language", "by_intent")


def fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.1%}"
    return str(value)


def metrics_table(metrics: Mapping) -> list:
    rows = ["| Metric | Value |", "| --- | --- |"]
    rows += [f"| {name} | {fmt(metrics[name])} |" for name in METRIC_ORDER if name in metrics]
    return rows


def breakdown_table(title: str, groups: Mapping) -> list:
    rows = [f"**{title}**", "", "| Group | Cases | Accuracy |", "| --- | --- | --- |"]
    rows += [f"| {name} | {row['cases']} | {fmt(row['accuracy_all_questions'])} |" for name, row in groups.items()]
    return rows + [""]


def render_markdown(report: Mapping) -> str:
    dataset = report["dataset"]
    lines = [
        "# Evaluation protocol report",
        "",
        f"Dataset version {dataset['version']}, digest `{dataset['digest'][:12]}`.",
        f"Cases in report scope: {sum(section['metrics']['cases'] for section in report['splits'].values())}.",
        f"Cases without a result: {len(report['missing_results'])}.",
        "",
    ]
    for split, section in report["splits"].items():
        lines += [f"## Split: {split}", ""] + metrics_table(section["metrics"]) + [""]
        statistics = section.get("statistics")
        if statistics:
            interval = statistics["interval"]
            span = "n/a" if interval is None else f"{interval[0]:.1%} to {interval[1]:.1%}"
            lines += [
                f"Verdict: **{statistics['verdict']}** (instances: {statistics['instances']}, interval: {span}, basis: {statistics['basis']}).",
                "",
            ]
        for key in BREAKDOWNS:
            lines += breakdown_table(key, section[key])
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: Mapping, directory: Path, stem: str = "eval_protocol_baseline") -> tuple:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
