"""Generate draft documentary cases (complete lists of a document) with the document as ground truth."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import RAG_DOCS_PATH
from core.evaluation.frozen_cases import parse_cases
from core.evaluation.instances import default_environment, find_spec
from core.evaluation.oracles.common import DEFAULT_USER, write_draft
from core.evaluation.oracles.documentation import MIN_ITEMS, collect_sections, sections_to_cases

DEFAULT_SPECS = PROJECT_ROOT / "core" / "evaluation" / "protocol" / "instances.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate draft documentary cases, the documents being the ground truth.")
    parser.add_argument("--instance", required=True, help="instance the cases are attached to (the corpus is shared)")
    parser.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    parser.add_argument("--documents", type=Path, default=Path(RAG_DOCS_PATH))
    parser.add_argument("--min-items", type=int, default=MIN_ITEMS)
    parser.add_argument("--limit", type=int, default=None)
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
    sections = collect_sections(args.documents, args.min_items)
    cases, skipped = sections_to_cases(spec, sections, args.limit, args.user)
    parse_cases(cases)
    output = args.output or env.output_dir / "drafts" / f"documentation_{spec.name}.json"
    write_draft(cases, output)
    print(f"{len(cases)} draft cases ({len(sections)} list sections, {len(skipped)} skipped) -> {output}")
    for reason in skipped:
        print(f"skipped: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
