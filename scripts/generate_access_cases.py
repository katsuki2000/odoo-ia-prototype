from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.oracles.access import (
    DEFAULT_MODELS,
    OPERATIONS,
    query_access_matrix,
    rows_to_cases,
)
from core.evaluation.frozen_cases import parse_cases
from core.evaluation.oracles.common import write_draft
from core.evaluation.instances import default_environment, find_spec

DEFAULT_SPECS = PROJECT_ROOT / "core" / "evaluation" / "protocol" / "instances.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate draft access-right cases, with Odoo as the oracle.")
    parser.add_argument("--instance", required=True)
    parser.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    parser.add_argument("--models", nargs="*", default=list(DEFAULT_MODELS))
    parser.add_argument("--users", nargs="*", default=[])
    parser.add_argument("--operations", nargs="*", default=list(OPERATIONS))
    parser.add_argument("--max-users", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = default_environment()
    spec = find_spec(args.specs, args.instance)
    if spec is None:
        print(f"unknown instance: {args.instance}")
        return 1
    rows = query_access_matrix(spec, env, models=args.models, users=args.users,
                               operations=args.operations, max_users=args.max_users)
    cases = rows_to_cases(spec, rows)
    parse_cases(cases)
    output = args.output or env.output_dir / "drafts" / f"access_{spec.name}.json"
    write_draft(cases, output)
    print(f"{len(cases)} draft cases ({len(rows)} oracle rows) -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
