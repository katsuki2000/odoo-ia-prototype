"""Run the frozen evaluation protocol over the evaluation instances and write the report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.frozen_cases import check_against_instances, load_dataset
from core.evaluation.instances import default_environment, load_specs
from core.evaluation.preflight import BackendUnavailable, require_backends
from core.evaluation.protocol_metrics import Preregistration, evaluate
from core.evaluation.protocol_report import write_report
from core.evaluation.protocol_runner import collect_results, load_ratings, run_protocol, split_summary

PROTOCOL_DIR = PROJECT_ROOT / "core" / "evaluation" / "protocol"
CAPTURES_DIR = PROJECT_ROOT / "captures"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen evaluation protocol and write the report.")
    parser.add_argument("--dataset", type=Path, default=PROTOCOL_DIR / "frozen_cases.json")
    parser.add_argument("--instances", type=Path, default=PROTOCOL_DIR / "instances.json")
    parser.add_argument("--preregistration", type=Path, default=PROTOCOL_DIR / "preregistration.json")
    parser.add_argument("--raw-dir", type=Path, default=CAPTURES_DIR / "eval_protocol_raw")
    parser.add_argument("--report-dir", type=Path, default=CAPTURES_DIR)
    parser.add_argument("--ratings", type=Path, default=None)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--case-ids", nargs="+", default=None, metavar="CASE_ID")
    parser.add_argument("--score-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = load_dataset(args.dataset)
    if args.case_ids is not None:
        from core.evaluation.protocol_runner import select_cases

        dataset = select_cases(dataset, args.case_ids)
    specs = load_specs(args.instances)
    check_against_instances(dataset, specs)
    if not dataset.cases:
        print("the frozen dataset has no cases")
        return 1
    print(f"dataset version {dataset.version}: {split_summary(dataset)}")
    raw_dir = args.raw_dir / f"v{dataset.version}_{dataset.digest[:12]}"
    print(f"raw responses: {raw_dir}")
    failures = []
    if not args.score_only:
        try:
            require_backends()
        except BackendUnavailable as error:
            print(f"model backend unavailable, no run started: {error}")
            return 2
        failures = run_protocol(dataset, specs, default_environment(), raw_dir, PROJECT_ROOT, args.only)
    report = evaluate(
        dataset,
        collect_results(dataset, raw_dir),
        Preregistration.load(args.preregistration),
        load_ratings(args.ratings),
    )
    report_stem = (
        f"eval_protocol_batch_{'_'.join(args.case_ids)}"
        if args.case_ids is not None
        else "eval_protocol_baseline"
    )
    json_path, markdown_path = write_report(report, args.report_dir, stem=report_stem)
    print(f"report -> {json_path} and {markdown_path}")
    for failure in failures:
        print(f"  {failure['name']}: {failure['error']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
