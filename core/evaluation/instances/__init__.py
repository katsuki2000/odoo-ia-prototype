"""Reproducible Odoo instances for the frozen evaluation protocol."""

from core.evaluation.instances.spec import (
    find_spec,
    InstanceSpec,
    load_specs,
    SPLITS,
)
from core.evaluation.instances.environment import (
    BuildEnvironment,
    database_name,
    default_environment,
    missing_modules,
    resolve_addon_roots,
)
from core.evaluation.instances.odoo_process import (
    build_shell_script,
    inspect_command,
    INSPECTION_MARKER,
    install_command,
    odoo_command,
    parse_inspection,
    parse_marked_json,
    postgres_environment,
    require_success,
    run_command,
    Runner,
)
from core.evaluation.instances.pinning import (
    directory_digest,
    file_digest,
    git_head,
    pin_modules,
)
from core.evaluation.instances.manifest import (
    merge_manifests,
    write_manifest,
)
from core.evaluation.instances.builder import (
    build_all,
    build_instance,
)

__all__ = [
    "build_all",
    "build_instance",
    "build_shell_script",
    "BuildEnvironment",
    "database_name",
    "default_environment",
    "directory_digest",
    "file_digest",
    "find_spec",
    "git_head",
    "inspect_command",
    "INSPECTION_MARKER",
    "install_command",
    "InstanceSpec",
    "load_specs",
    "merge_manifests",
    "missing_modules",
    "odoo_command",
    "parse_inspection",
    "parse_marked_json",
    "pin_modules",
    "postgres_environment",
    "require_success",
    "resolve_addon_roots",
    "run_command",
    "Runner",
    "SPLITS",
    "write_manifest",
]
