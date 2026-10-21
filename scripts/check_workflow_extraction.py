"""Print the states and the state writes the extractor derives for one Odoo model, from the real addons."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.graph.state_field import lifecycle_field
from code_intelligence.graph.workflow_extraction import selection_values, written_states
from config.settings import CORE_ADDONS_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--file", required=True, help="path of the model file, relative to the core addons directory")
    parser.add_argument("--buttons", nargs="+", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(CORE_ADDONS_PATH) / args.file
    if not path.is_file():
        print(f"file not found: {path}")
        return 1
    decls = [decl for decl in extract_odoo_models_from_file(path) if decl.name == args.model]
    if not decls:
        print(f"model {args.model} is not declared in {path}")
        return 1
    state_field = lifecycle_field(decls)
    print(f"{args.model} state field: {state_field} ; values: {selection_values(decls, state_field) if state_field else None}")
    for button in args.buttons:
        print(f"  {button} -> {written_states(decls, button, state_field) if state_field else []}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
