from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.frozen_cases import parse_cases
from core.evaluation.instances import default_environment, find_spec
from core.evaluation.oracles.ambiguity import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_MODULES,
    query_ambiguous_terms,
    rows_to_cases,
)
from core.evaluation.oracles.common import DEFAULT_USER, write_draft

DEFAULT_SPECS = PROJECT_ROOT / "core" / "evaluation" / "protocol" / "instances.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate draft ambiguity cases from the instance, with Odoo as the oracle.")
    parser.add_argument("--instance", required=True)
    parser.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    parser.add_argument("--min-modules", type=int, default=DEFAULT_MIN_MODULES)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = default_environment()
    spec = find_spec(args.specs, args.instance)
    if spec is None:
        print(f"unknown instance: {args.instance}")
        return 1
    rows = query_ambiguous_terms(spec, env, min_modules=args.min_modules)
    cases = rows_to_cases(spec, rows, args.limit, args.user)
    parse_cases(cases)
    output = args.output or env.output_dir / "drafts" / f"ambiguity_{spec.name}.json"
    write_draft(cases, output)
    print(f"{len(cases)} draft cases ({len(rows)} ambiguous terms) -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
