from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.frozen_cases import (
    check_against_instances,
    dataset_from_payload,
    freeze_dataset,
    load_dataset,
    write_dataset,
)
from core.evaluation.instances import load_specs

PROTOCOL_DIR = PROJECT_ROOT / "core" / "evaluation" / "protocol"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a draft of evaluation cases and freeze it with a new version.")
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--output", type=Path, default=PROTOCOL_DIR / "frozen_cases.json")
    parser.add_argument("--instances", type=Path, default=PROTOCOL_DIR / "instances.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    draft = json.loads(args.draft.read_text(encoding="utf-8"))
    rows = draft["cases"] if isinstance(draft, dict) else draft
    if args.output.is_file():
        current = load_dataset(args.output).version
        if args.version <= current:
            print(f"version must be greater than the current frozen version ({current})")
            return 1
    payload = freeze_dataset(rows, args.version)
    check_against_instances(dataset_from_payload(payload), load_specs(args.instances))
    write_dataset(payload, args.output)
    print(f"frozen {len(payload['cases'])} cases, version {args.version}, digest {payload['digest'][:12]} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
