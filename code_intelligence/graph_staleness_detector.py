"""
code_intelligence/graph_staleness_detector.py

Incremental Graph Staleness Detector:
- Level 0 (CLEAN): No changes detected.
- Level 1 (FILE_ONLY): Direct nodes associated with changed files are marked dirty.
- Level 2 (PROPAGATION): Adjacent dependent nodes/edges are marked propagated.
- Level 3 (FULL_REBUILD): Uncovered dynamic patterns or manifest/ACL changes require full graph rebuild.
"""

import ast
import hashlib
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any, Union
import logging
import networkx as nx

_logger = logging.getLogger(__name__)


class StalenessLevel(IntEnum):
    CLEAN = 0
    FILE_ONLY = 1        # Level 1: Direct file-only node invalidation
    PROPAGATION = 2      # Level 2: Adjacency/inheritance edge propagation
    FULL_REBUILD = 3     # Level 3: Dynamic or systemic change requiring full rebuild


# Backwards compatibility level aliases
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


# Level 3 dynamic pattern triggers
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
    """Build a mapping of file_path_str -> sha256_hash."""
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
    """
    J39: Scan a changed Python file for uncovered dynamic constructs
    that invalidate local static analysis (getattr, safe_eval, eval, exec, importlib).
    Returns the reason string if found, else None.
    """
    if not filepath.exists() or filepath.suffix != ".py":
        return None

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return f"failed to read file {filepath.name}: {e}"

    for pattern in _DYNAMIC_DISPATCH_PATTERNS:
        match = pattern.search(content)
        if match:
            # Find line number
            line_no = content[:match.start()].count("\n") + 1
            pattern_str = match.group(0).strip(" (")
            return f"dynamic {pattern_str} detected in {filepath.name}:L{line_no}"

    return None


def get_nodes_for_filepath(G: nx.DiGraph, filepath_str: str) -> List[str]:
    """
    J37 Level 1: Find all node IDs in graph associated with a given filepath.
    """
    clean_fp = str(Path(filepath_str).resolve())
    dirty_nodes = set()

    for node, attrs in G.nodes(data=True):
        node_fp = attrs.get("filepath")
        if node_fp:
            if str(Path(node_fp).resolve()) == clean_fp:
                dirty_nodes.add(node)
                continue

        # Check list of filepaths on model nodes (source_files or filepaths)
        filepaths = attrs.get("filepaths") or attrs.get("source_files") or []
        if filepaths:
            for fp in filepaths:
                if str(Path(fp).resolve()) == clean_fp:
                    dirty_nodes.add(node)
                    break

    return sorted(list(dirty_nodes))


def propagate_dirty_nodes(G: nx.DiGraph, dirty_nodes: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    J38 Level 2: Propagate dirty state along adjacent dependency edges
    (EXTENDS, RESTRICTED_BY, HAS_FIELD, DEFINED_IN, IMPLIES, RELATES_TO).
    Returns (propagated_node_ids, affected_cross_edges).
    """
    propagated = set()
    visited = set(dirty_nodes)
    queue = list(dirty_nodes)
    affected_edges = set()

    sensitive_edges = {"EXTENDS", "RESTRICTED_BY", "HAS_FIELD", "DEFINED_IN", "IMPLIES", "RELATES_TO"}

    while queue:
        curr = queue.pop(0)
        # Outgoing edges
        for neighbor in G.successors(curr):
            edge_data = G.get_edge_data(curr, neighbor) or {}
            edge_type = edge_data.get("edge_type", "")
            if edge_type in sensitive_edges:
                affected_edges.add((curr, neighbor))
                if neighbor not in visited:
                    visited.add(neighbor)
                    propagated.add(neighbor)
                    queue.append(neighbor)

        # Incoming edges (reverse dependencies)
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
    """
    Main Staleness Detector entry point (J37-J39):
    Analyses a list of changed filepaths against graph G and returns a StalenessReport.
    """
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

        # Level 3 Check: Manifest or ACL CSV changes require full rebuild
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

        # Level 3 Check: Dynamic uncovered Python patterns (getattr, safe_eval, eval, exec)
        dynamic_reason = _detect_dynamic_uncovered_patterns(p)
        if dynamic_reason:
            return StalenessReport(
                level=StalenessLevel.FULL_REBUILD,
                reason=dynamic_reason,
                changed_files=changed_filepaths,
                changed_modules=changed_modules,
            )

        # Level 1: Find direct dirty nodes for this file
        nodes = get_nodes_for_filepath(G, path_str)
        dirty_nodes_set.update(nodes)

    dirty_nodes = sorted(list(dirty_nodes_set))

    if not dirty_nodes:
        # File changed but not currently indexed in graph (e.g. new file, deleted file, or rename) -> Level 3 full rebuild
        reason_msg = "potential rename or unindexed file added/deleted in codebase"
        return StalenessReport(
            level=StalenessLevel.FULL_REBUILD,
            reason=reason_msg,
            changed_files=changed_filepaths,
            changed_modules=changed_modules,
        )

    # Level 2: Propagate along dependency edges
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


class GraphStalenessDetector:
    """Class wrapper around analyze_changes for object-oriented usage."""

    def __init__(
        self,
        G: Optional[nx.DiGraph] = None,
        graph: Optional[nx.DiGraph] = None,
        file_hash_index: Optional[Dict[str, str]] = None,
        module_roots: Optional[Dict[str, Path]] = None,
    ):
        self.G = G if G is not None else (graph if graph is not None else nx.DiGraph())
        self.file_hash_index = file_hash_index or {}
        self.module_roots = module_roots or {}

    def scan_changed_files(self, old_index: Optional[Dict[str, str]] = None) -> Tuple[List[str], List[str]]:
        """Scan module_roots against old_index to detect changed, added or deleted files."""
        if old_index is None:
            old_index = self.file_hash_index

        changed_files = []
        changed_modules = set()

        # Scan files on disk
        for mod_name, mod_root in self.module_roots.items():
            root_p = Path(mod_root)
            if not root_p.exists():
                continue
            for f in root_p.rglob("*"):
                if f.is_file() and f.suffix in {".py", ".xml", ".csv"}:
                    f_str = str(f.resolve())
                    curr_hash = compute_file_hash(f)
                    old_hash = old_index.get(f_str)
                    if old_hash != curr_hash:
                        changed_files.append(f_str)
                        changed_modules.add(mod_name)

        # Check for deleted files
        for old_f in old_index.keys():
            if not Path(old_f).exists() and old_f not in changed_files:
                changed_files.append(old_f)
                for mod_name, mod_root in self.module_roots.items():
                    if old_f.startswith(str(Path(mod_root).resolve())):
                        changed_modules.add(mod_name)

        return changed_files, sorted(list(changed_modules))

    def detect_staleness(
        self,
        changed_files: Optional[List[str]] = None,
        old_index: Optional[Dict[str, str]] = None,
        old_hash_index: Optional[Dict[str, str]] = None,
    ) -> StalenessReport:
        effective_old_index = old_hash_index if old_hash_index is not None else old_index

        if changed_files is None:
            changed_files, changed_modules = self.scan_changed_files(effective_old_index)
        else:
            changed_modules = []

        return analyze_changes(
            changed_files,
            self.G,
            module_roots=self.module_roots,
            changed_modules_override=changed_modules if changed_modules else None,
        )

    def analyze(
        self,
        old_index: Optional[Dict[str, str]] = None,
        old_hash_index: Optional[Dict[str, str]] = None,
        changed_files: Optional[List[str]] = None,
    ) -> StalenessReport:
        return self.detect_staleness(changed_files=changed_files, old_index=old_index, old_hash_index=old_hash_index)

    def detect(
        self,
        old_hash_index: Optional[Dict[str, str]] = None,
        old_index: Optional[Dict[str, str]] = None,
        changed_files: Optional[List[str]] = None,
    ) -> StalenessReport:
        return self.detect_staleness(changed_files=changed_files, old_index=old_index, old_hash_index=old_hash_index)
