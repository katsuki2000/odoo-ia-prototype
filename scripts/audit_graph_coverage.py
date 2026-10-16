#!/usr/bin/env python3
"""Read-only audit: compare the active graph with the Odoo artefacts present in the module sources.

Usage:
    python scripts/audit_graph_coverage.py [--graph PATH] [--output PATH]
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_intelligence.evaluation.graph_source_audit import build_source_audit
from code_intelligence.graph.atomic_swap import atomic_read_json
from code_intelligence.graph.loader import GRAPH_JSON_PATH
from code_intelligence.graph.version import deserialize_graph_with_metadata

DEFAULT_OUTPUT = PROJECT_ROOT / "captures" / "graph_source_audit.json"
TOP_UNEXTRACTED_KINDS = 25


def format_report(report: dict) -> str:
    lines = [
        f"modules audited: {report['modules_audited']}  without local source: {len(report['modules_without_source'])}",
        f"{'kind':<28}{'status':<16}{'disk':>8}{'graph':>8}{'missing':>9}{'extra':>7}",
    ]
    unextracted = 0
    for row in report["kinds"]:
        if row["status"] == "not_extracted":
            unextracted += 1
            if unextracted > TOP_UNEXTRACTED_KINDS:
                continue
        lines.append(
            f"{row['kind']:<28}{row['status']:<16}{row['disk']:>8}"
            f"{row.get('graph', ''):>8}{row.get('missing', ''):>9}{row.get('extra', ''):>7}"
        )
    if unextracted > TOP_UNEXTRACTED_KINDS:
        lines.append(f"... {unextracted - TOP_UNEXTRACTED_KINDS} more not_extracted kinds in the JSON report")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit graph coverage against module sources.")
    parser.add_argument("--graph", type=Path, default=GRAPH_JSON_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    graph, metadata = deserialize_graph_with_metadata(atomic_read_json(args.graph))
    report = build_source_audit(graph)
    report["graph"] = {"path": args.graph.name, "git_commit": metadata.get("git_commit", "unknown"),
                       "fingerprint": graph.graph.get("instance_fingerprint")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(format_report(report))
    print(f"\nreport written to {args.output}")


if __name__ == "__main__":
    main()
