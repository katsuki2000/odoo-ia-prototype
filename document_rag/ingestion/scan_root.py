"""Resolve and validate filesystem roots used for document ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from config.settings import RAG_DOCS_PATH

DOCS_DIR = Path(RAG_DOCS_PATH)
DEFAULT_SCAN_ROOT_CANDIDATES: tuple[Path, ...] = (DOCS_DIR,)


def resolve_scan_root(file_path: Path, candidate_roots: Iterable[Path]) -> Path | None:
    """Return the most specific configured root containing file_path."""
    resolved_file = Path(file_path).resolve()
    matching_roots = []
    for candidate in candidate_roots:
        root = Path(candidate).resolve()
        if resolved_file == root:
            continue
        try:
            resolved_file.relative_to(root)
        except ValueError:
            continue
        matching_roots.append(root)
    return max(matching_roots, key=lambda root: len(root.parts), default=None)


def confine_to_scan_roots(
    path: Path | str,
    candidate_roots: Iterable[Path] = DEFAULT_SCAN_ROOT_CANDIDATES,
) -> Path:
    """Resolve a path and reject it unless it is contained in an approved scan root."""
    resolved = Path(path).resolve()
    for candidate in candidate_roots:
        root = Path(candidate).resolve()
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError("Path is outside configured ingestion roots.")


def compute_source(file_path: Path, scan_root: Path | None) -> str:
    """Return a portable source path relative to scan_root when possible."""
    path = Path(file_path)
    if scan_root is not None:
        try:
            return str(path.resolve().relative_to(Path(scan_root).resolve()))
        except ValueError:
            pass
    return str(path)


def ensure_docs_dir() -> Path:
    """Create the configured document root when ingestion or scanning starts."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    return DOCS_DIR
