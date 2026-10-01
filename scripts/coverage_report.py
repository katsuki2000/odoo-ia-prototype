#!/usr/bin/env python3
"""Report graph coverage from either current or legacy graph JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_intelligence.evaluation.graph_coverage import build_graph_coverage_report
from code_intelligence.graph.version import deserialize_graph_with_metadata


def load_graph(path: Path):
    """Load a graph JSON envelope and retain its serialization metadata."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return deserialize_graph_with_metadata(payload)


def render_text(report: dict) -> str:
    """Render the stable human-readable view of a coverage report."""
    lines = ["=== Graph coverage ==="]
    if report["instance_fingerprint"]:
        lines.append(f"Instance fingerprint: {report['instance_fingerprint']}")
    if report["language"]:
        lines.append(f"Language: {report['language']}")
    for name, data in report["coverage"].items():
        ratio = "n/a" if data["ratio"] is None else f"{data['ratio']:.1%}"
        lines.append(f"{name}: {data['covered']}/{data['total']} ({ratio})")
    gaps = report["unresolved_menu_actions"]
    lines.append(f"Unresolved menu actions: {len(gaps)}")
    for gap in gaps[:15]:
        lines.append(
            f"  - {gap['node_id']} (name={gap['name']!r}, action_ref={gap['action_ref']!r})"
        )
    inventory = report["runtime_inventory"]
    if inventory["available"]:
        lines.append(f"Unindexed installed modules: {len(inventory['unindexed_installed_modules'])}")
        lines.extend(f"  - {module}" for module in inventory["unindexed_installed_modules"][:15])
    else:
        lines.append("Runtime module inventory: unavailable")
    translations = report["runtime_translations"]
    if translations["queried_languages"]:
        lines.append(
            "Runtime translations: "
            f"{translations['attached']} attached, {translations['unlinked']} unlinked "
            f"for {', '.join(translations['queried_languages'])}"
        )
    elif translations["active_languages_available"]:
        lines.append("Runtime translations: no requested active language")
    else:
        lines.append("Runtime translations: unavailable")
    lines.append(f"Unresolved graph references: {len(report['unresolved_references'])}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("--language")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    if not args.graph.is_file():
        parser.error(f"graph file does not exist: {args.graph}")
    graph, metadata = load_graph(args.graph)
    report = build_graph_coverage_report(graph, language=args.language)
    report["graph_metadata"] = metadata
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
