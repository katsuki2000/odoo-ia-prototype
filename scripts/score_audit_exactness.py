#!/usr/bin/env python3
"""Note un rapport d'audit de resolution sur l'EXACTITUDE (journal D-14), sans relancer l'audit.

Usage : python scripts/score_audit_exactness.py [rapport.json] [--expected tests/expected_models.json]
Par defaut : captures/question_resolution_audit.json. Les questions sans verite etablie ne sont pas notees.
"""

import argparse
import collections
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.expected_models import DEFAULT_PATH, EXACT, load_expected_models, classify_resolution  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", type=Path, default=PROJECT_ROOT / "captures" / "question_resolution_audit.json")
    parser.add_argument("--expected", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    expected, tolerated = load_expected_models(args.expected)
    rows = json.loads(args.report.read_text(encoding="utf-8"))
    counts = collections.Counter()
    scored = 0
    for row in rows:
        qid = row["id"]
        if qid not in expected:
            continue
        scored += 1
        verdict = classify_resolution(row.get("models", []), expected[qid], tolerated[qid])
        counts[verdict] += 1
        server = f" serveur={row['server']}" if row.get("server") else ""
        print(f"{verdict.upper():<10} {qid:<7} attendu={sorted(expected[qid])} obtenu={row.get('models', [])}{server}")
    resolved = sum(1 for row in rows if row.get("resolved"))
    print(f"\n{counts[EXACT]}/{scored} exacts sur les questions avec verite etablie "
          f"({', '.join(f'{k} {v}' for k, v in counts.items() if k != EXACT) or 'aucun autre cas'}) ; "
          f"{resolved}/{len(rows)} resolues au sens de l'audit")


if __name__ == "__main__":
    main()
