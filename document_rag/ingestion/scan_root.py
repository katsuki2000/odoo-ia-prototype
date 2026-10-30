"""Portable source identifiers and path validation for document ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from config.settings import RAG_DOCS_PATH

DOCS_DIR = Path(RAG_DOCS_PATH)
DEFAULT_SCAN_ROOT_CANDIDATES = [DOCS_DIR]


def resolve_scan_root(file_path: Path, candidate_roots: Iterable[Path]) -> Path | None:
    """Return the most specific configured root containing the file."""
    resolved_file = Path(file_path).resolve()
    roots = (Path(root).resolve() for root in candidate_roots)
    matches = (root for root in roots if resolved_file != root and resolved_file.is_relative_to(root))
    return max(matches, key=lambda root: len(root.parts), default=None)


def confine_to_scan_roots(
    path: Path | str,
    candidate_roots: Iterable[Path] = DEFAULT_SCAN_ROOT_CANDIDATES,
) -> Path:
    """Resolve a path and reject files outside configured ingestion roots."""
    resolved = Path(path).resolve()
    if any(resolved.is_relative_to(Path(root).resolve()) for root in candidate_roots):
        return resolved
    raise ValueError("Path is outside configured ingestion roots.")


def compute_source(file_path: Path, scan_root: Path | None = None) -> str:
    """Return a portable source path, relative to its ingestion root when known.

    Direct loader calls without a root use the filename; batch ingestion must
    provide its root to distinguish files with the same name.
    """
    path = Path(file_path).resolve()
    if scan_root is not None:
        try:
            return str(path.relative_to(Path(scan_root).resolve()))
        except ValueError:
            pass
    return path.name
