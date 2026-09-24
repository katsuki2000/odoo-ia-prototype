"""
AST extraction of calls made through a Many2one relational field of the
model being analyzed (e.g. `move.company_id._get_user_fiscal_lock_date()`),
resolved to their comodel via the knowledge graph. Complements
code_intelligence.rules.source_callees, which only follows calls on the
SAME model -- this follows calls onto a RELATED model (todo/contexte.txt
sections 934/935, point J: ACC-Q2, account.move._check_fiscalyear_lock_date
delegates the real group-based exemption logic to
res.company._get_user_fiscal_lock_date via the company_id field, never
read by the same-model-only mechanism).
"""

import ast
import textwrap
from typing import Dict, List, Tuple

_SECURITY_EXCEPTION_NAMES = frozenset({
    "UserError", "ValidationError", "AccessDenied", "AccessError",
})
_GROUP_CHECK_METHODS = frozenset({"has_group", "user_has_groups"})


def get_relational_fields(G, model_name: str) -> Dict[str, str]:
    """Many2one fields of `model_name`, mapped to their comodel name."""
    model_node = f"model:{model_name}"
    if model_node not in G:
        return {}
    fields: Dict[str, str] = {}
    for _, field_node, attrs in G.out_edges(model_node, data=True):
        if attrs.get("edge_type") != "HAS_FIELD":
            continue
        field_attrs = G.nodes[field_node]
        comodel = field_attrs.get("comodel_name")
        field_type = (field_attrs.get("field_type") or "").lower()
        if comodel and field_type == "many2one":
            fields[field_attrs.get("name", "")] = comodel
    return fields


def _raised_exception_name(node: ast.Raise) -> str:
    exc = node.exc
    if isinstance(exc, ast.Call):
        if isinstance(exc.func, ast.Name):
            return exc.func.id
        if isinstance(exc.func, ast.Attribute):
            return exc.func.attr
    elif isinstance(exc, ast.Name):
        return exc.id
    elif isinstance(exc, ast.Attribute):
        return exc.attr
    return ""


def _is_security_relevant_function(node) -> bool:
    """True if this function raises a security exception, or checks a
    group membership -- the same scope PythonSecurityLockAnalysis already
    treats as a security lock, so relational callees are only followed
    from methods actually relevant to a security-lock question, not from
    every unrelated method that happens to touch the same field."""
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and _raised_exception_name(child) in _SECURITY_EXCEPTION_NAMES:
            return True
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in _GROUP_CHECK_METHODS
        ):
            return True
    return False


def source_is_security_relevant(source: str) -> bool:
    """True if `source` (a method body) raises a security exception or checks
    a group membership. Used to keep only related-model callees that carry
    lock logic, so a generic helper (e.g. currency.compare_amounts) reached
    from a security-relevant method does not consume the follow-up budget."""
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return False
    return _is_security_relevant_function(tree)


def extract_relational_lock_callees(
    source: str, relational_fields: Dict[str, str]
) -> List[Tuple[str, str, str, str]]:
    """Calls of the shape `<var>.<relational_field>.<method>(...)`, found
    inside a security-relevant function of `source`, resolved via
    `relational_fields` to (caller_method_name, field_name, method_name,
    comodel_name). Source order, deduplicated."""
    if not relational_fields:
        return []
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return []

    found: List[Tuple[int, int, str, str, str, str]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_security_relevant_function(func):
            continue
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            field_access = node.func.value
            if not (isinstance(field_access, ast.Attribute) and isinstance(field_access.value, ast.Name)):
                continue
            comodel = relational_fields.get(field_access.attr)
            if not comodel:
                continue
            found.append((node.lineno, node.col_offset, func.name, field_access.attr, node.func.attr, comodel))

    seen = set()
    result: List[Tuple[str, str, str, str]] = []
    for _, _, caller, field_name, method_name, comodel in sorted(found):
        key = (caller, field_name, method_name)
        if key in seen:
            continue
        seen.add(key)
        result.append((caller, field_name, method_name, comodel))
    return result
