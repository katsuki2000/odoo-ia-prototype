"""Build environment and addons resolution for evaluation instances."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from config import settings
from core.evaluation.instances.spec import InstanceSpec


@dataclass(frozen=True)
class BuildEnvironment:
    odoo_python: str
    odoo_bin: str
    odoo_conf: Optional[str]
    core_addons: str
    custom_addons: str
    oca_root: Optional[str]
    db_prefix: str
    output_dir: Path


def default_environment() -> BuildEnvironment:
    return BuildEnvironment(
        odoo_python=settings.EVAL_ODOO_PYTHON,
        odoo_bin=settings.EVAL_ODOO_BIN,
        odoo_conf=settings.EVAL_ODOO_CONF,
        core_addons=settings.CORE_ADDONS_PATH,
        custom_addons=settings.CUSTOM_ADDONS_PATH,
        oca_root=settings.OCA_SAMPLE_ADDONS_PATH,
        db_prefix=settings.EVAL_DB_PREFIX,
        output_dir=Path(settings.EVAL_INSTANCES_DIR),
    )


def resolve_addon_roots(spec: InstanceSpec, env: BuildEnvironment) -> dict:
    fixed = {"core": env.core_addons, "custom": env.custom_addons}
    roots = {}
    for label in spec.addons:
        if label in fixed:
            base = fixed[label]
        elif label.startswith("oca/") and env.oca_root:
            base = Path(env.oca_root) / label[len("oca/"):]
        else:
            raise ValueError(f"{spec.name}: cannot resolve addons label '{label}'")
        path = Path(base)
        if not path.is_dir():
            raise FileNotFoundError(f"{spec.name}: addons directory missing for '{label}'")
        roots[label] = path.resolve()
    return roots


def missing_modules(spec: InstanceSpec, roots: Iterable[Path]) -> list:
    roots = list(roots)
    return [
        module for module in spec.modules
        if not any((root / module / "__manifest__.py").is_file() for root in roots)
    ]


def database_name(spec: InstanceSpec, prefix: str) -> str:
    return f"{prefix}{spec.name.lower()}"
