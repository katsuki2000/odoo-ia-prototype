"""
Structural (AST) extraction of the calls inside an Odoo method body that a
deterministic dispatcher should follow: calls to other button_* methods, calls
used as a condition (if/while/assert tests, comprehension filters,
filtered/all/any arguments), then any other call delegated to a method of the
same model. Conditions decide "in which case" questions, and a delegated call
describes a step of the flow: both bodies must be read, not guessed from the
method name.
"""

import ast
import textwrap
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

_PREDICATE_FUNCTIONS = frozenset({"filtered", "filter", "all", "any"})
_BUTTON_PREFIX = "button_"
_FRAMEWORK_METHODS = frozenset({
    "write", "create", "unlink", "copy", "browse", "search", "search_count", "read", "read_group",
    "mapped", "filtered", "filtered_domain", "sorted", "ensure_one", "exists", "with_context",
    "with_user", "with_company", "with_env", "flush_model", "flush_recordset",
    "invalidate_model", "invalidate_recordset", "message_post", "message_subscribe",
    "message_unsubscribe", "get", "pop", "update", "append", "extend", "join", "format",
})

_Position = Tuple[int, int]


def read_method_source(filepath: str, lineno: int, end_lineno: int) -> Optional[str]:
    try:
        lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return "\n".join(lines[max(lineno, 1) - 1:end_lineno])


def _parse(source: str) -> Optional[ast.AST]:
    try:
        return ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return None


def _function_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _method_calls(node: ast.AST) -> Iterator[Tuple[_Position, str]]:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
        ):
            yield (child.lineno, child.col_offset), child.func.attr


def _receiver_root(node: ast.AST) -> Optional[ast.Name]:
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        node = node.func.value
    return node if isinstance(node, ast.Name) else None


def _delegated_calls(node: ast.AST) -> Iterator[Tuple[_Position, str]]:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr not in _FRAMEWORK_METHODS
            and _receiver_root(child.func.value) is not None
        ):
            yield (child.lineno, child.col_offset), child.func.attr


def _predicate_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            yield node.test
        elif isinstance(node, ast.comprehension):
            yield from node.ifs
        elif isinstance(node, ast.Call) and _function_name(node) in _PREDICATE_FUNCTIONS:
            yield from node.args
            yield from (keyword.value for keyword in node.keywords)


def _names_in_source_order(calls: List[Tuple[_Position, str]]) -> List[str]:
    return [name for _, name in sorted(set(calls))]


def extract_followable_callees(source: str, own_method: str) -> List[str]:
    tree = _parse(source)
    if tree is None:
        return []
    button_calls = _names_in_source_order(
        [call for call in _method_calls(tree) if call[1].startswith(_BUTTON_PREFIX)]
    )
    predicate_calls = _names_in_source_order(
        [call for node in _predicate_nodes(tree) for call in _method_calls(node)]
    )
    delegated_calls = _names_in_source_order(list(_delegated_calls(tree)))
    ordered = dict.fromkeys(button_calls + predicate_calls + delegated_calls)
    ordered.pop(own_method, None)
    return list(ordered)


def extract_has_group_literals(source: str) -> List[str]:
    tree = _parse(source)
    if tree is None:
        return []
    found = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "has_group"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    return list(dict.fromkeys(found))


def inspect_noop_hook_method(source: str) -> Optional[Tuple[str, str]]:
    """Inspect Python source text of a method/function slice to determine if it defines
    a no-op hook (empty body, pass, return True/False/None/Ellipsis, return empty container,
    or raise NotImplementedError).
    Returns (func_name, noop_description) if a no-op hook is detected, else None.
    """
    if not source or not source.strip():
        return None
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return None

    functions: List[ast.FunctionDef | ast.AsyncFunctionDef] = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if len(functions) != 1:
        if len(tree.body) == 1 and isinstance(tree.body[0], ast.ClassDef):
            class_methods = [
                n for n in tree.body[0].body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if len(class_methods) == 1:
                functions = class_methods
            else:
                return None
        else:
            return None

    func = functions[0]
    body_stmts = [
        s for s in func.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
    ]

    if not body_stmts:
        return func.name, "corps vide / docstring uniquement"

    if len(body_stmts) == 1:
        stmt = body_stmts[0]
        if isinstance(stmt, ast.Pass):
            return func.name, "pass"
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                return func.name, "retourne None"
            if isinstance(stmt.value, ast.Constant):
                val = stmt.value.value
                if val is True:
                    return func.name, "retourne True"
                if val is False:
                    return func.name, "retourne False"
                if val is None:
                    return func.name, "retourne None"
                if val == ...:
                    return func.name, "retourne Ellipsis (...)"
            if isinstance(stmt.value, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
                elts = getattr(stmt.value, "elts", None)
                keys = getattr(stmt.value, "keys", None)
                if not elts and not keys:
                    return func.name, "retourne un conteneur vide"
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value == ...:
            return func.name, "..."
        if isinstance(stmt, ast.Raise):
            exc = stmt.exc
            exc_name = None
            if isinstance(exc, ast.Name):
                exc_name = exc.id
            elif isinstance(exc, ast.Call):
                if isinstance(exc.func, ast.Name):
                    exc_name = exc.func.id
                elif isinstance(exc.func, ast.Attribute):
                    exc_name = exc.func.attr
            if exc_name == "NotImplementedError":
                return func.name, "lève NotImplementedError"

    return None


def format_noop_hook_note(func_name: str, noop_desc: str) -> str:
    return (
        f"[NOTE DÉTERMINISTIQUE -- HOOK SANS EFFET / NO-OP]\n"
        f"La méthode '{func_name}' est un hook sans effet / no-op ({noop_desc}). "
        f"Elle n'exécute aucun traitement actif par défaut dans ce module (aucun calcul, modification ou validation). "
        f"Ne PAS lui attribuer d'effet métier dans la réponse (par exemple, elle ne valide ni ne recalcule rien).\n"
        f"(NO-OP HOOK: '{func_name}' is a no-op ({noop_desc}) and performs no business action or validation. "
        f"Do NOT attribute any effect to it in the answer.)"
    )

