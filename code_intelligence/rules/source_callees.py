"""Detect no-op hook methods (empty body, pass, trivial return, NotImplementedError) from source text."""

import ast
import textwrap
from typing import List, Optional, Tuple


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
