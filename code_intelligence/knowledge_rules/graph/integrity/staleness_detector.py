"""
Incremental Graph Staleness Detector.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import logging
import networkx as nx

from .staleness_models import (
    StalenessLevel,
    StalenessReport,
    STALENESS_LEVEL_FILE,
    STALENESS_LEVEL_EDGE,
    STALENESS_LEVEL_UNCOVERABLE,
    _DYNAMIC_DISPATCH_PATTERNS,
    compute_file_hash,
    build_file_hash_index,
    _detect_dynamic_uncovered_patterns,
)

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
        if old_index is None:
            old_index = self.file_hash_index

        changed_files = []
        changed_modules = set()

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
