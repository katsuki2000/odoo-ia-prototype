"""Build, inspect and pin reproducible Odoo instances for the frozen evaluation protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from code_intelligence.graph.instance_fingerprint import build_instance_fingerprint
from core.evaluation.instances.environment import (
    BuildEnvironment,
    database_name,
    missing_modules,
    resolve_addon_roots,
)
from core.evaluation.instances.odoo_process import (
    INSPECTION_SCRIPT,
    Runner,
    inspect_command,
    install_command,
    parse_inspection,
    postgres_environment,
    require_success,
    run_command,
)
from core.evaluation.instances.pinning import file_digest, git_head, pin_modules
from core.evaluation.instances.spec import InstanceSpec


def build_instance(
    spec: InstanceSpec,
    env: BuildEnvironment,
    runner: Runner = run_command,
    install: bool = True,
    dump: bool = False,
) -> dict:
    roots = resolve_addon_roots(spec, env)
    absent = missing_modules(spec, roots.values())
    if absent:
        raise ValueError(f"{spec.name}: modules not found in addons paths: {absent}")
    database = database_name(spec, env.db_prefix)
    paths = list(roots.values())
    logs = env.output_dir / "logs"
    if install:
        require_success(
            runner(install_command(spec, env, paths, database), None),
            f"install {spec.name}", logs / f"{spec.name}_install.log",
        )
    inspection = parse_inspection(require_success(
        runner(inspect_command(env, paths, database), INSPECTION_SCRIPT),
        f"inspect {spec.name}", logs / f"{spec.name}_inspect.log",
    ).stdout)
    fingerprint = build_instance_fingerprint(inspection["modules"], paths, inspection["languages"], spec.language)
    installed = [row["name"] for row in inspection["modules"]]
    entry = {
        "name": spec.name,
        "split": spec.split,
        "database": database,
        "language": spec.language,
        "with_demo": spec.with_demo,
        "requested_modules": list(spec.modules),
        "addons": list(spec.addons),
        "odoo_version": inspection["version"],
        "core_git_head": git_head(Path(env.core_addons).parent, runner),
        "installed_modules": sorted(
            [row["name"], row.get("installed_version") or "", row["state"]] for row in inspection["modules"]
        ),
        "pinned_modules": pin_modules(installed, roots),
        "fingerprint_digest": fingerprint.digest,
        "dump": None,
    }
    if dump:
        env.output_dir.mkdir(parents=True, exist_ok=True)
        target = env.output_dir / f"{spec.name}.dump"
        try:
            require_success(
                runner(["pg_dump", "-Fc", "-f", str(target), database], None, postgres_environment(env.odoo_conf)),
                f"dump {spec.name}", logs / f"{spec.name}_dump.log",
            )
            entry["dump"] = {"file": target.name, "sha256": file_digest(target)}
        except RuntimeError as error:
            entry["dump"] = {"error": str(error)}
    return entry


def build_all(
    specs: Iterable[InstanceSpec],
    env: BuildEnvironment,
    runner: Runner = run_command,
    install: bool = True,
    dump: bool = False,
) -> dict:
    manifest = {"instances": [], "failures": []}
    for spec in specs:
        try:
            entry = build_instance(spec, env, runner, install, dump)
            manifest["instances"].append(entry)
            if entry["dump"] and "error" in entry["dump"]:
                manifest["failures"].append({"name": spec.name, "error": entry["dump"]["error"]})
        except (RuntimeError, ValueError, FileNotFoundError) as error:
            manifest["failures"].append({"name": spec.name, "error": str(error)})
    return manifest
