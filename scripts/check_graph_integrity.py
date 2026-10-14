"""Inspect a serialized graph without changing it or contacting Odoo."""

import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('graph', type=Path, help='Path to the serialized node-link graph')
    args = parser.parse_args()
    modulePath = Path(__file__).resolve().parents[1] / 'code_intelligence/graph/integrity_report.py'
    spec = importlib.util.spec_from_file_location('graph_integrity_report', modulePath)
    reportModule = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reportModule)
    try:
        payload = json.loads(args.graph.read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('Expected a JSON object.')
        report = reportModule.inspect_serialized_graph(payload)
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f'Cannot inspect graph: {error}\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report['issue_count'] or report['unresolved_reference_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
