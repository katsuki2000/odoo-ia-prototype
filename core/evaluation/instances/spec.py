"""Evaluation instance specifications."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


SPLITS = ("calibration", "held_out")


@dataclass(frozen=True)
class InstanceSpec:
    name: str
    split: str
    modules: tuple
    language: str
    with_demo: bool
    addons: tuple

    @classmethod
    def from_dict(cls, data: Mapping) -> "InstanceSpec":
        spec = cls(
            name=data["name"],
            split=data["split"],
            modules=tuple(data["modules"]),
            language=data["language"],
            with_demo=bool(data["with_demo"]),
            addons=tuple(data["addons"]),
        )
        if spec.split not in SPLITS:
            raise ValueError(f"{spec.name}: split must be one of {SPLITS}")
        if not spec.modules:
            raise ValueError(f"{spec.name}: no modules to install")
        return spec


def load_specs(path: Path) -> list:
    specs = [InstanceSpec.from_dict(row) for row in json.loads(Path(path).read_text(encoding="utf-8"))]
    names = [spec.name for spec in specs]
    if len(set(names)) != len(names):
        raise ValueError("duplicate instance names")
    return specs


def find_spec(path: Path, name: str) -> Optional[InstanceSpec]:
    return next((spec for spec in load_specs(path) if spec.name == name), None)
