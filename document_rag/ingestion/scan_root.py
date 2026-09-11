"""
Canonical scan-root definitions and helpers shared by the ingestion
pipeline (ingest_all.py, incremental.py, watcher.py) and loaders
(wiki_loader.py, pdf_loader.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from config.settings import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, RAG_DOCS_PATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent


DOCS_DIR = Path(RAG_DOCS_PATH)
CORE_ADDONS_ROOT = Path(CORE_ADDONS_PATH)
CUSTOM_ADDONS_ROOT = Path(CUSTOM_ADDONS_PATH)

# The 3 logical roots the ingestion pipeline actually scans. Used as the
# default candidate list for resolve_scan_root() wherever a caller doesn't
# know (or care) which specific root a file belongs under -- e.g. a single
# file path handed to the watcher on a filesystem event.
DEFAULT_SCAN_ROOT_CANDIDATES: list[Path] = [DOCS_DIR, CORE_ADDONS_ROOT, CUSTOM_ADDONS_ROOT]


def resolve_scan_root(file_path: Path, candidate_roots: Iterable[Path]) -> Optional[Path]:
    """Return the most specific candidate root that contains file_path.

    Picks the candidate with the longest resolved path (most specific
    ancestor), so a module directory nested under a broader watched root
    still resolves against the tightest applicable match. Returns None if
    no candidate root actually contains file_path (caller should then fall
    back to an absolute `source`, e.g. compute_source() below).
    """
    resolved_file = Path(file_path).resolve()
    best: Optional[Path] = None
    for candidate in candidate_roots:
        candidate = Path(candidate).resolve()
        if resolved_file == candidate:
            continue
        try:
            resolved_file.relative_to(candidate)
        except ValueError:
            continue
        if best is None or len(candidate.parts) > len(best.parts):
            best = candidate
    return best


def compute_source(file_path: Path, scan_root: Optional[Path]) -> str:
    """Return the `source` metadata value for a loaded file.

    Relative to scan_root when one is given and file_path is actually
    under it (portable, machine-independent). Falls back to the absolute
    path otherwise -- unchanged legacy behavior for callers that don't
    know their scan root (e.g. a loader called directly in a unit test).
    """
    if scan_root is not None:
        try:
            return str(Path(file_path).resolve().relative_to(Path(scan_root).resolve()))
        except ValueError:
            pass
    return str(file_path)


def resolve_absolute_source(
    source: str, candidate_roots: Iterable[Path] = DEFAULT_SCAN_ROOT_CANDIDATES
) -> Path:
    """Resolve a stored `source` metadata value back to an absolute path.

    Mirrors compute_source() in reverse. If `source` is already absolute
    (legacy chunks indexed before scan-root-relative sourcing existed, or
    a caller that passed no scan_root), it is returned resolved as-is.

    Otherwise `source` is joined against each candidate root in order; the
    first candidate whose parent directory exists on disk wins. Parent
    (not the file itself) is checked so this also works for sources whose
    file has since been deleted -- exactly the case incremental.py's
    deletion detection needs to resolve. Falls back to the first candidate
    root if none match (best effort; only reachable if every candidate
    root's relevant subdirectory is itself gone).
    """
    source_path = Path(source)
    if source_path.is_absolute():
        return source_path.resolve()

    candidates = list(candidate_roots)
    for candidate in candidates:
        joined = Path(candidate).resolve() / source_path
        if joined.parent.exists():
            return joined


    if candidates:
        return Path(candidates[0]).resolve() / source_path
    return source_path.resolve()
