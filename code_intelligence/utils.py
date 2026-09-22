"""Shared utilities for the Code Intelligence pipeline."""

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Set

__all__ = [
    "SENSITIVE_BYPASS_MARKER",
    "format_xml_id_citation",
    "format_xml_id_citations",
    "format_file_link",
    "resolve_model_xmlref",
    "discover_odoo_modules",
    "compute_addons_hash",
    "fold_accents",
    "_TRUNCATION_MARKER",
    "_TRUNCATION_PROXIMITY_CHARS",
    "_match_near_truncation",
    "_AMOUNT_PATTERN",
    "_extract_amount",
    "_APPROVAL_PATTERN",
    "_question_is_approval_related",
    "_CAN_VIEW_FACT_VERDICT_RE",
    "_CAN_VIEW_FACT_INDETERMINATE_MARKER",
    "_split_before_first_fact_marker",
    "_has_can_view_amount_fact",
    "_LOCK_CONDITION_LINE_RE",
    "_AMOUNT_CMP_RE",
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


# ── Model & module resolution ───────────────────────────────────────────────

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


# ── Text-signal primitives ──────────────────────────────────────────────────

_TRUNCATION_MARKER = "\n[... Content truncated for LLM context limit ...]"
_TRUNCATION_PROXIMITY_CHARS = 50


def _match_near_truncation(text: str, start: int, end: int) -> bool:
    """True if [start, end) span is within proximity of a truncation marker."""
    ws = max(0, start - _TRUNCATION_PROXIMITY_CHARS)
    we = min(len(text), end + _TRUNCATION_PROXIMITY_CHARS)
    return _TRUNCATION_MARKER in text[ws:we]


# Section 883: "Ar" (Ariary) est la seule devise non-EUR vue dans le corpus.
# Case-sensible (pas de re.IGNORECASE sur ce token) pour eviter tout mot
# francais courant se terminant en "ar"/"AR" -- (?i:...) limite
# l'insensibilite a la casse au seul groupe eur/EUR.
_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:(?i:€|eur(?:os?)?\b)|Ar\b)")


def _extract_amount(question: str) -> Optional[float]:
    """Extract first monetary amount mentioned in question as a float."""
    match = _AMOUNT_PATTERN.search(question)
    if not match:
        return None
    raw = match.group(0)
    numeric_part = re.sub(r"(?i)(€|eur(?:os?)?)|Ar\b", "", raw).strip()
    cleaned = numeric_part.replace(" ", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


_APPROVAL_PATTERN = re.compile(
    r"\b(?:approuv\w*|valid\w*|approbation\w*|permission\w*|exig\w*|condition\w*|rembourse\w*)\b",
    re.IGNORECASE,
)


def _question_is_approval_related(question: str) -> bool:
    return bool(_APPROVAL_PATTERN.search(question))


_CAN_VIEW_FACT_VERDICT_RE = re.compile(
    r"can_view_amount\(\)\s*=\s*(True|False)\s*:\s*l.utilisateur\s+(PEUT|NE PEUT PAS)",
)
_CAN_VIEW_FACT_INDETERMINATE_MARKER = "can_view_amount_v2() = indeterminate"


def _split_before_first_fact_marker(text: str) -> str:
    """Text portion before the first '[FAIT' marker."""
    idx = text.find("[FAIT")
    return text if idx == -1 else text[:idx]


def _has_can_view_amount_fact(final_answer: str) -> bool:
    return bool(_CAN_VIEW_FACT_VERDICT_RE.search(final_answer)) or (
        _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    )


_LOCK_CONDITION_LINE_RE = re.compile(
    r"\*\s*\"[^\"]*\"\s*\(condition\s*:\s*(.*?has_group\(['\"]([^'\"]+)['\"]\).*?)\)",
    re.IGNORECASE,
)
_AMOUNT_CMP_RE = re.compile(
    r"(?:rec\.)?amount(?:_total)?\s*(>|>=|<|<=)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
