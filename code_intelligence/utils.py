"""
code_intelligence/utils.py

Shared utilities for the Code Intelligence pipeline.
"""

import hashlib
from pathlib import Path
from typing import List, Optional, Set

# Bloc 7 (J23-24, revised): shared marker used to tag, AT THE SOURCE, the
# specific lines within a tool's summary_text that describe an actual
# security-bypass mechanism (hardcoded privileged logins, sudo() escaping
# ir.rule/ACL, hardcoded ID lists granting undocumented special treatment)
# -- as opposed to normal governance/uncertainty information (which groups
# can approve, dynamic-dispatch confidence caveats), which must NOT be
# marked and stays visible to every requester regardless of their rights.
#
# Decision (after J23-24 review): gating the ENTIRE tool observation
# whenever a requester lacked elevated rights on the model made routine
# governance questions ("qui peut approuver un avoir ?") unanswerable for
# most requesters, since analyze_security_locks mixes both kinds of
# content in one block. Tagging at the source lets authorization_gate.py
# redact only the specific marked line(s), leaving the rest of the answer
# intact. Defined here (not in authorization_gate.py) so the Bloc 2
# analyzers (semgrep_locks_analyzer.py, server_action_analyzer.py) that
# produce this text don't need to depend on the later Bloc 7 gating module
# -- both sides import this single shared constant instead.
SENSITIVE_BYPASS_MARKER = "[SENSITIVE BYPASS]"


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
