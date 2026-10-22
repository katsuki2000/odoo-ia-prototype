"""
Data structures and dynamic pattern detectors for graph staleness.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import networkx as nx


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
    except OSError as err:
        _logger.warning("Cannot hash %s: %s", p, err)
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

# ── Staleness analysis ───────────────────────────────────────────────────

_logger = logging.getLogger(__name__)


def get_nodes_for_filepath(G: nx.DiGraph, filepath_str: str) -> List[str]:
    """Find all node IDs in graph associated with a given filepath."""
    clean_fp = str(Path(filepath_str).resolve())
    dirty_nodes = set()

    for node, attrs in G.nodes(data=True):
        node_fp = attrs.get("filepath")
        if node_fp and str(Path(node_fp).resolve()) == clean_fp:
            dirty_nodes.add(node)
            continue

        filepaths = attrs.get("filepaths") or attrs.get("source_files") or []
        if filepaths:
            for fp in filepaths:
                if str(Path(fp).resolve()) == clean_fp:
                    dirty_nodes.add(node)
                    break

    return sorted(list(dirty_nodes))


def propagate_dirty_nodes(G: nx.DiGraph, dirty_nodes: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Propagate dirty state along adjacent dependency edges."""
    propagated = set()
    visited = set(dirty_nodes)
    queue = list(dirty_nodes)
    affected_edges = set()

    sensitive_edges = {"EXTENDS", "RESTRICTED_BY", "HAS_FIELD", "DEFINED_IN", "IMPLIES", "RELATES_TO"}

    while queue:
        curr = queue.pop(0)
        for neighbor in G.successors(curr):
            edge_data = G.get_edge_data(curr, neighbor) or {}
            edge_type = edge_data.get("edge_type", "")
            if edge_type in sensitive_edges:
                affected_edges.add((curr, neighbor))
                if neighbor not in visited:
                    visited.add(neighbor)
                    propagated.add(neighbor)
                    queue.append(neighbor)

        for predecessor in G.predecessors(curr):
            edge_data = G.get_edge_data(predecessor, curr) or {}
            edge_type = edge_data.get("edge_type", "")
            if edge_type in sensitive_edges:
                affected_edges.add((predecessor, curr))
                if predecessor not in visited:
                    visited.add(predecessor)
                    propagated.add(predecessor)
                    queue.append(predecessor)

    return sorted(list(propagated)), sorted(list(affected_edges))


def analyze_changes(
    changed_filepaths: List[str],
    G: nx.DiGraph,
    module_roots: Optional[Dict[str, Path]] = None,
    changed_modules_override: Optional[List[str]] = None,
) -> StalenessReport:
    """Analyze changed filepaths against graph G and return a StalenessReport."""
    if not changed_filepaths:
        return StalenessReport(level=StalenessLevel.CLEAN, reason="no files changed")

    changed_mods_set = set(changed_modules_override or [])
    if module_roots:
        for mod_name, mod_root in module_roots.items():
            mod_root_str = str(Path(mod_root).resolve())
            for fp in changed_filepaths:
                if str(Path(fp).resolve()).startswith(mod_root_str):
                    changed_mods_set.add(mod_name)

    if not changed_mods_set:
        for path_str in changed_filepaths:
            p = Path(path_str)
            parts = p.parts
            if "addons" in parts:
                idx = parts.index("addons")
                if idx + 1 < len(parts):
                    changed_mods_set.add(parts[idx + 1])
            else:
                for part in parts:
                    if part not in {"tmp", "pytest-of-user", "var", "usr", "home", "/"}:
                        changed_mods_set.add(part)
                        break

    changed_modules = sorted(list(changed_mods_set))
    dirty_nodes_set: Set[str] = set()

    for path_str in changed_filepaths:
        p = Path(path_str)
        filename = p.name.lower()

        if filename in {"__manifest__.py", "__openerp__.py"}:
            return StalenessReport(
                level=StalenessLevel.FULL_REBUILD,
                reason=f"manifest file changed: {p.name}",
                changed_files=changed_filepaths,
                changed_modules=changed_modules,
            )

        if filename == "ir.model.access.csv":
            return StalenessReport(
                level=StalenessLevel.FULL_REBUILD,
                reason=f"global access control CSV changed: {p.name}",
                changed_files=changed_filepaths,
                changed_modules=changed_modules,
            )

        dynamic_reason = _detect_dynamic_uncovered_patterns(p)
        if dynamic_reason:
            return StalenessReport(
                level=StalenessLevel.FULL_REBUILD,
                reason=dynamic_reason,
                changed_files=changed_filepaths,
                changed_modules=changed_modules,
            )

        nodes = get_nodes_for_filepath(G, path_str)
        dirty_nodes_set.update(nodes)

    dirty_nodes = sorted(list(dirty_nodes_set))
    if not dirty_nodes:
        return StalenessReport(
            level=StalenessLevel.FULL_REBUILD,
            reason="potential rename or unindexed file added/deleted in codebase",
            changed_files=changed_filepaths,
            changed_modules=changed_modules,
        )

    propagated_nodes, affected_cross_edges = propagate_dirty_nodes(G, dirty_nodes)
    level = StalenessLevel.PROPAGATION if propagated_nodes else StalenessLevel.FILE_ONLY
    reason = (
        f"Level 2: {len(dirty_nodes)} direct dirty nodes + {len(propagated_nodes)} propagated nodes"
        if level == StalenessLevel.PROPAGATION
        else f"Level 1: {len(dirty_nodes)} direct dirty nodes, zero propagation"
    )

    return StalenessReport(
        level=level,
        dirty_nodes=dirty_nodes,
        propagated_nodes=propagated_nodes,
        reason=reason,
        changed_files=changed_filepaths,
        changed_modules=changed_modules,
        affected_cross_edges=affected_cross_edges,
    )
