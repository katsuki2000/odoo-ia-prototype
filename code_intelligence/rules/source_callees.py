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
