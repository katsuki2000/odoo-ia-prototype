"""
Data structures and dynamic pattern detectors for graph staleness.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class StalenessLevel(IntEnum):
    CLEAN = 0
    FILE_ONLY = 1
    PROPAGATION = 2
    FULL_REBUILD = 3


STALENESS_LEVEL_FILE = StalenessLevel.FILE_ONLY
STALENESS_LEVEL_EDGE = StalenessLevel.PROPAGATION
STALENESS_LEVEL_UNCOVERABLE = StalenessLevel.FULL_REBUILD


@dataclass
class StalenessReport:
    """Structured report produced by graph staleness analysis."""
    level: StalenessLevel
    dirty_nodes: List[str] = field(default_factory=list)
    propagated_nodes: List[str] = field(default_factory=list)
    reason: str = ""
    changed_files: List[str] = field(default_factory=list)
    changed_modules: List[str] = field(default_factory=list)
    affected_cross_edges: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def requires_full_rebuild(self) -> bool:
        return self.level == StalenessLevel.FULL_REBUILD

    @property
    def is_clean(self) -> bool:
        return self.level == StalenessLevel.CLEAN

    @property
    def is_stale(self) -> bool:
        return self.level != StalenessLevel.CLEAN

    @property
    def has_uncoverable_cases(self) -> bool:
        return self.level == StalenessLevel.FULL_REBUILD

    @property
    def uncoverable_reasons(self) -> List[str]:
        return [self.reason] if self.reason and self.has_uncoverable_cases else []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": int(self.level),
            "dirty_nodes": self.dirty_nodes,
            "propagated_nodes": self.propagated_nodes,
            "reason": self.reason,
            "changed_files": self.changed_files,
            "changed_modules": self.changed_modules,
            "affected_cross_edges": self.affected_cross_edges,
            "has_uncoverable_cases": self.has_uncoverable_cases,
            "uncoverable_reasons": self.uncoverable_reasons,
            "is_stale": self.is_stale,
        }


_DYNAMIC_DISPATCH_PATTERNS = [
    re.compile(r"\bgetattr\s*\("),
    re.compile(r"\bsafe_eval\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bimportlib\.import_module\s*\("),
    re.compile(r"\b__import__\s*\("),
]


def compute_file_hash(filepath: Path) -> str:
    """Compute sha256 hash of a file for staleness comparison."""
    p = Path(filepath)
    if not p.exists():
        return ""
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return ""


def build_file_hash_index(files: Union[List[Path], Path, str]) -> Dict[str, str]:
    """Build mapping of file_path_str -> sha256_hash."""
    index = {}
    if isinstance(files, (Path, str)):
        p = Path(files)
        if p.is_dir():
            file_list = [f for f in p.rglob("*") if f.is_file()]
        else:
            file_list = [p] if p.exists() else []
    else:
        file_list = [Path(f) for f in files if Path(f).exists()]

    for f in file_list:
        index[str(f.resolve())] = compute_file_hash(f)
    return index


def _detect_dynamic_uncovered_patterns(filepath: Path) -> Optional[str]:
    """Scan changed Python file for dynamic constructs."""
    if not filepath.exists() or filepath.suffix != ".py":
        return None

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return f"failed to read file {filepath.name}: {e}"

    for pattern in _DYNAMIC_DISPATCH_PATTERNS:
        match = pattern.search(content)
        if match:
            line_no = content[:match.start()].count("\n") + 1
            pattern_str = match.group(0).strip(" (")
            return f"dynamic {pattern_str} detected in {filepath.name}:L{line_no}"

    return None
