"""Portable source path of a loaded document."""

from pathlib import Path


def compute_source(file_path: Path, scan_root: Path | None) -> str:
    """Return the path relative to scan_root when possible."""
    path = Path(file_path)
    if scan_root is not None:
        try:
            return str(path.resolve().relative_to(Path(scan_root).resolve()))
        except ValueError:
            pass
    return str(path)
