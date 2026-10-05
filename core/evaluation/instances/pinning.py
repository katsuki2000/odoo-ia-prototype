"""Content digests and git revisions that pin an evaluation instance."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Mapping, Optional

from core.evaluation.instances.odoo_process import Runner


def directory_digest(path: Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    files = sorted(
        item for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    )
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pin_modules(installed: Iterable[str], roots: Mapping[str, Path]) -> dict:
    pins = {}
    for label, root in roots.items():
        if label == "core":
            continue
        for name in installed:
            if (root / name / "__manifest__.py").is_file():
                pins.setdefault(label, {})[name] = directory_digest(root / name)
    return pins


def git_head(path: Path, runner: Runner) -> Optional[str]:
    result = runner(["git", "-C", str(path), "rev-parse", "HEAD"], None)
    return result.stdout.strip() if result.returncode == 0 else None
