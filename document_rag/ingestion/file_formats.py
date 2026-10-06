"""Document formats the ingestion pipeline can read."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".docx"})
OFFICE_LOCK_PREFIX = "~$"


def is_supported_document(path: str | Path) -> bool:
    """Return True for a readable document format, ignoring Office lock files."""
    path = Path(path)
    return path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith(OFFICE_LOCK_PREFIX)
