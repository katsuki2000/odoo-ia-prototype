"""Shared utilities for the Code Intelligence pipeline."""

import ast
import hashlib
import logging
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Optional, Set

_logger = logging.getLogger(__name__)

__all__ = [
    "SENSITIVE_BYPASS_MARKER",
    "format_xml_id_citation",
    "format_xml_id_citations",
    "format_file_link",
    "qualify_xml_id",
    "resolve_model_xmlref",
    "discover_odoo_modules",
    "compute_addons_hash",
    "fold_accents",
    "read_source_text",
    "parse_python_text",
    "_TRUNCATION_MARKER",
    "waterfill_budget",
]

SENSITIVE_BYPASS_MARKER = "[SENSITIVE BYPASS]"


def waterfill_budget(sizes: List[int], total_budget: int) -> List[int]:
    """Fair-share allocation of a fixed budget across items of varying size.

    An item that fits within its current fair share (total_budget divided
    by however many items are still unsettled) keeps its full size; the
    unused surplus is redistributed across the remaining items, repeated
    until the budget is exhausted or every item is settled. Classic
    water-filling allocation (the same principle used for bandwidth/power
    allocation): guarantees no single item can starve another purely by
    being listed first, listed last, or being unusually large -- unlike a
    naive "join everything then truncate from the head" strategy.
    """
    n = len(sizes)
    if n == 0 or total_budget <= 0:
        return [0] * n

    allocation = [0] * n
    remaining_indices = list(range(n))
    remaining_budget = total_budget

    while remaining_indices:
        share = remaining_budget // len(remaining_indices)
        settled = [i for i in remaining_indices if sizes[i] <= share]
        if not settled:
            per_item, leftover = divmod(remaining_budget, len(remaining_indices))
            for k, i in enumerate(remaining_indices):
                allocation[i] = per_item + (1 if k < leftover else 0)
            break
        for i in settled:
            allocation[i] = sizes[i]
            remaining_budget -= sizes[i]
        remaining_indices = [i for i in remaining_indices if i not in settled]

    return allocation


# ── Formatting helpers ──────────────────────────────────────────────────────

def format_xml_id_citation(identifier: str) -> str:
    """Format a single Odoo XML-ID into a citation token."""
    if not identifier or "." not in identifier:
        return ""
    return f"xml_id: {identifier}"


def format_xml_id_citations(identifiers) -> str:
    """Space-joined 'xml_id: ...' tokens for every valid identifier."""
    tokens = [format_xml_id_citation(i) for i in identifiers]
    return " ".join(t for t in tokens if t)


def format_file_link(
    filepath: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str:
    """Format a file path into a clickable GitHub-style markdown link."""
    if not filepath:
        return ""
    basename = Path(filepath).name
    if start_line is not None and end_line is not None:
        return f"[{basename}:L{start_line}-L{end_line}](file://{filepath}#L{start_line}-L{end_line})"
    elif start_line is not None:
        return f"[{basename}:L{start_line}](file://{filepath}#L{start_line})"
    return f"[{basename}](file://{filepath})"


_ABSOLUTE_FILE_LINK = re.compile(r"file://(/[^#)\s]+)")


def relativize_file_links(text: str, roots: Iterable[str]) -> str:
    """Make absolute file links machine independent: keep the path from the addons folder name onward."""
    rootPaths = sorted((Path(root) for root in roots), key=lambda root: len(root.parts), reverse=True)

    def relative(match: re.Match) -> str:
        path = Path(match.group(1))
        for root in rootPaths:
            if path.is_relative_to(root):
                return f"file://{path.relative_to(root.parent)}"
        return match.group(0)

    return _ABSOLUTE_FILE_LINK.sub(relative, text)


# ── Model & module resolution ───────────────────────────────────────────────

def qualify_xml_id(xml_id: str, module: str) -> str:
    """Prefix a bare XML id with the module that declares it."""
    return xml_id if "." in xml_id else f"{module}.{xml_id}"


def resolve_model_xmlref(raw_ref: str) -> str:
    """Convert an Odoo XML model reference to its technical model name."""
    if not raw_ref:
        return raw_ref
    working = raw_ref
    if "." in working and "model_" in working:
        working = working.split(".", 1)[-1]
    if working.startswith("model_"):
        return working[len("model_"):].replace("_", ".")
    return raw_ref


def discover_odoo_modules(
    addons_path: Path,
    prefix: Optional[str] = None,
    include: Optional[List[str]] = None,
    exclude: Optional[Set[str]] = None,
) -> List[str]:
    """Auto-discover Odoo modules in an addons directory."""
    if not addons_path.exists():
        return []
    if exclude is None:
        exclude = set()
    modules = []
    for d in sorted(addons_path.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "__manifest__.py").exists():
            continue
        if d.name in exclude:
            continue
        if include is not None and d.name not in include:
            continue
        if prefix is not None and not d.name.startswith(prefix):
            continue
        modules.append(d.name)
    return modules


def compute_addons_hash(
    addons_path: Path, module_names: Optional[List[str]] = None
) -> str:
    """SHA-256 hash (first 16 hex chars) of all source files in given modules."""
    h = hashlib.sha256()
    if module_names:
        dirs = [addons_path / m for m in sorted(module_names) if (addons_path / m).exists()]
    else:
        dirs = [addons_path]
    for base_dir in dirs:
        for ext in ("*.py", "*.xml", "*.csv"):
            for f in sorted(base_dir.rglob(ext)):
                h.update(f.read_bytes())
    return h.hexdigest()[:16]


def fold_accents(text: str) -> str:
    """Normalize text: lowercase + strip diacritics."""
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()


def read_source_text(path) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        _logger.warning("Cannot read source file %s: %s", path, err)
        return None


def parse_python_text(text: str, path) -> Optional[ast.Module]:
    try:
        return ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError, RecursionError) as err:
        _logger.warning("Cannot parse Python source %s: %s", path, err)
        return None


# ── Text-signal primitives ──────────────────────────────────────────────────

_TRUNCATION_MARKER = "\n[... Content truncated for LLM context limit ...]"
