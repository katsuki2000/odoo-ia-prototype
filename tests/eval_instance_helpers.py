"""Shared builders for the evaluation instance tests."""

from pathlib import Path

from core.evaluation import instances as ib


def make_module(root: Path, name: str, content: str = "x") -> Path:
    module = root / name
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text("{}", encoding="utf-8")
    (module / "models.py").write_text(content, encoding="utf-8")
    return module


def make_env(tmp_path: Path, oca: bool = False) -> ib.BuildEnvironment:
    core = tmp_path / "odoo" / "addons"
    custom = tmp_path / "custom"
    core.mkdir(parents=True)
    custom.mkdir()
    oca_root = None
    if oca:
        oca_root = tmp_path / "oca"
        (oca_root / "sale-workflow").mkdir(parents=True)
    return ib.BuildEnvironment(
        odoo_python="odoo-python",
        odoo_bin="odoo-bin",
        odoo_conf=None,
        core_addons=str(core),
        custom_addons=str(custom),
        oca_root=str(oca_root) if oca_root else None,
        db_prefix="eval_",
        output_dir=tmp_path / "out",
    )


def make_spec(**overrides) -> ib.InstanceSpec:
    data = {
        "name": "Demo",
        "split": "held_out",
        "modules": ["sale"],
        "language": "fr_FR",
        "with_demo": True,
        "addons": ["core"],
    }
    data.update(overrides)
    return ib.InstanceSpec.from_dict(data)
