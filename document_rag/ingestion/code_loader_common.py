"""
document_rag/ingestion/code_loader_common.py

Shared utilities for code document loaders (hashing, token estimation, module extraction).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional


def compute_hash(text: str) -> str:
    """Compute SHA-256 hash of text content."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def estimate_tokens(splitter: Any, text: str) -> int:
    """
    Cheap token-count estimate used to decide whether a structural
    chunk (XML element / JS unit) needs further splitting.
    """
    try:
        return len(splitter._tokenizer.encode(text))
    except Exception:
        return len(text) // 4


def extract_module_name(file_path: Path | str, scan_root: Optional[Path | str] = None) -> str:
    """Extract module name from file path relative to scan_root."""
    if scan_root is not None:
        try:
            rel = Path(file_path).resolve().relative_to(Path(scan_root).resolve())
        except ValueError:
            rel = None
        if rel is not None and rel.parts:
            return rel.parts[0]
    return "unknown"
