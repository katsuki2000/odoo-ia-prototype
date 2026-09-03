"""
code_intelligence/utils.py

Shared utilities for the Code Intelligence pipeline.
"""

import hashlib
from pathlib import Path
from typing import List, Optional, Set

SENSITIVE_BYPASS_MARKER = "[SENSITIVE BYPASS]"


def format_xml_id_citation(identifier: str) -> str:
    """Format a single Odoo technical identifier (rule/group/action xml_id)
    as the 'xml_id: module.identifier' sourcing-citation token that
    code_intelligence/sourcing_guard.py's _XML_ID_PATTERN looks for as
    ground truth. Root cause (todo/contexte.txt section 490): CI_SYSTEM_PROMPT
    instructs the synthesis LLM to copy this exact prefix "verbatim from the
    source observation", but no tool observation ever emitted it -- this is
    the single place every tool formatter should go through instead of each
    reimplementing the "xml_id: " prefix separately (F-08 duplication rule).

    Returns "" for an identifier that isn't a real module-qualified xml_id
    (no dot) -- never emits a citation token for something that wouldn't
    match the guard's own pattern anyway.
    """
    if not identifier or "." not in identifier:
        return ""
    return f"xml_id: {identifier}"


def format_xml_id_citations(identifiers) -> str:
    """Space-joined 'xml_id: ...' tokens for every valid identifier in
    `identifiers`, skipping any format_xml_id_citation rejects. Each token
    is emitted separately, never comma-joined -- sourcing_guard's
    _XML_ID_PATTERN stops at the first non-identifier character, so a
    comma-joined list would only ever yield the first id as ground truth."""
    tokens = [format_xml_id_citation(i) for i in identifiers]
    return " ".join(t for t in tokens if t)


def format_file_link(filepath: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """Format a file path and line numbers into a clickable GitHub-style markdown link.

    Examples:
      format_file_link('/path/to/models/hr_leave.py', 12, 25)
      -> '[hr_leave.py:L12-L25](file:///path/to/models/hr_leave.py#L12-L25)'
      format_file_link('/path/to/security/rules.xml')
      -> '[rules.xml](file:///path/to/security/rules.xml)'
    """
    if not filepath:
        return ""

    p = Path(filepath)
    basename = p.name

    if start_line is not None and end_line is not None:
        return f"[{basename}:L{start_line}-L{end_line}](file://{filepath}#L{start_line}-L{end_line})"
    elif start_line is not None:
        return f"[{basename}:L{start_line}](file://{filepath}#L{start_line})"
    else:
        return f"[{basename}](file://{filepath})"


def resolve_model_xmlref(raw_ref: str) -> str:
    """Convert an Odoo XML model reference to its technical model name.

    Handles all standard Odoo XML ref formats:
      - 'account.model_account_move'       -> 'account.move'
      - 'model_account_move'               -> 'account.move'
      - 'hr_expense.model_hr_expense_sheet' -> 'hr.expense.sheet'
      - 'model_hr_expense_sheet'            -> 'hr.expense.sheet'
      - 'sale.order'                        -> 'sale.order'  (already a model name)
      - 'account.move'                      -> 'account.move' (already a model name)

    The Odoo convention for XML model references is:
      <module_name>.model_<model_name_with_underscores>
    where dots in the model name are replaced by underscores.
    """
    if not raw_ref:
        return raw_ref

    # Strip module prefix if present (e.g. "account.model_account_move" -> "model_account_move")
    working = raw_ref
    if "." in working and "model_" in working:
        # e.g. "account.model_account_move" -> take "model_account_move"
        working = working.split(".", 1)[-1]

    if working.startswith("model_"):
        # "model_account_move" -> "account.move"
        # "model_hr_expense_sheet" -> "hr.expense.sheet"
        return working[len("model_"):].replace("_", ".")

    # Already a technical model name (e.g. "sale.order", "account.move")
    return raw_ref


def discover_odoo_modules(
    addons_path: Path,
    prefix: Optional[str] = None,
    include: Optional[List[str]] = None,
    exclude: Optional[Set[str]] = None,
) -> List[str]:
    """Auto-discover Odoo modules in an addons directory.

    A directory is considered an Odoo module if it contains a __manifest__.py file.

    Args:
        addons_path: Path to the addons directory to scan.
        prefix: If set, only return modules whose name starts with this prefix.
        include: If set, only return modules in this explicit list.
        exclude: If set, skip modules in this set.

    Returns:
        Sorted list of module directory names.
    """
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


def compute_addons_hash(addons_path: Path, module_names: Optional[List[str]] = None) -> str:
    """Compute a SHA-256 hash of all source files in the given modules.

    Used for cache invalidation: if the hash changes, the graph needs to be rebuilt.

    Args:
        addons_path: Path to the addons directory.
        module_names: If set, only hash files in these modules. Otherwise, hash all.

    Returns:
        First 16 hex chars of the SHA-256 digest.
    """
    h = hashlib.sha256()
    dirs = []
    if module_names:
        dirs = [addons_path / m for m in sorted(module_names) if (addons_path / m).exists()]
    else:
        dirs = [addons_path]

    for base_dir in dirs:
        for ext in ("*.py", "*.xml", "*.csv"):
            for f in sorted(base_dir.rglob(ext)):
                h.update(f.read_bytes())

    return h.hexdigest()[:16]
