from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.instances import (
    build_all,
    database_name,
    default_environment,
    install_command,
    inspect_command,
    load_specs,
    resolve_addon_roots,
    write_manifest,
)

DEFAULT_SPECS = PROJECT_ROOT / "core" / "evaluation" / "protocol" / "instances.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the evaluation Odoo instances and write their manifest.")
    parser.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = default_environment()
    specs = [spec for spec in load_specs(args.specs) if args.only is None or spec.name in args.only]
    if args.dry_run:
        for spec in specs:
            try:
                roots = list(resolve_addon_roots(spec, env).values())
            except (ValueError, FileNotFoundError) as error:
                print(f"{spec.name}: {error}")
                continue
            database = database_name(spec, env.db_prefix)
            print(shlex.join(install_command(spec, env, roots, database)))
            print(shlex.join(inspect_command(env, roots, database)))
        return 0
    manifest = build_all(specs, env, install=not args.inspect_only, dump=args.dump)
    target = write_manifest(manifest, env.output_dir)
    print(f"{len(manifest['instances'])} built, {len(manifest['failures'])} failed -> {target}")
    for failure in manifest["failures"]:
        print(f"  {failure['name']}: {failure['error']}")
    return 1 if manifest["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
