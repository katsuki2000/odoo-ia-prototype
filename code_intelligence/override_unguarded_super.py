"""AST static analysis check for unguarded super() calls in method overrides."""

import ast
import logging
from typing import List, Optional

_logger = logging.getLogger(__name__)


def _branch_returns_or_raises(stmts: List[ast.stmt]) -> bool:
    if not stmts:
        return False
    return isinstance(stmts[-1], (ast.Return, ast.Raise))


_STATE_MUTATING_CALL_NAMES = {"write", "update", "unlink"}


def _branch_mutates_record_state(stmts: List[ast.stmt]) -> bool:
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Attribute) for t in targets):
                    return True
            elif isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in _STATE_MUTATING_CALL_NAMES
                ):
                    return True
    return False


class _UnguardedSuperVisitor(ast.NodeVisitor):
    def __init__(self, method_name: str):
        self.method_name = method_name
        self._if_depth = 0
        self._for_loop_stack: List[str] = []
        self.non_returning_conditionals: List[tuple] = []
        self.unconditional_super_calls: List[tuple] = []

    def visit_For(self, node: ast.For):
        loop_var = self._filtered_source_name(node.iter)
        if loop_var:
            self._for_loop_stack.append(loop_var)
        self.generic_visit(node)
        if loop_var:
            self._for_loop_stack.pop()

    def visit_If(self, node: ast.If):
        if not _branch_returns_or_raises(node.body) and _branch_mutates_record_state(
            node.body
        ):
            condition_source = self._safe_unparse(node.test)
            loop_var = self._for_loop_stack[-1] if self._for_loop_stack else None
            self.non_returning_conditionals.append((node.lineno, condition_source, loop_var))
        self._if_depth += 1
        self.generic_visit(node)
        self._if_depth -= 1

    def visit_Call(self, node: ast.Call):
        if self._if_depth == 0 and self._is_super_call(node):
            excluded_var = self._extract_excluded_recordset_name(node.func.value)
            self.unconditional_super_calls.append((node.lineno, excluded_var))
        self.generic_visit(node)

    @staticmethod
    def _safe_unparse(node: ast.expr) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return "?"

    @staticmethod
    def _filtered_source_name(node: ast.expr) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        return None

    @staticmethod
    def _extract_excluded_recordset_name(super_call: ast.Call) -> Optional[str]:
        if len(super_call.args) < 2:
            return None
        expr = super_call.args[1]
        if (
            isinstance(expr, ast.BinOp)
            and isinstance(expr.op, ast.Sub)
            and isinstance(expr.left, ast.Name)
            and expr.left.id == "self"
            and isinstance(expr.right, ast.Name)
        ):
            return expr.right.id
        return None

    def _is_super_call(self, node: ast.Call) -> bool:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != self.method_name:
            return False
        value = func.value
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "super"
        )

    @staticmethod
    def _is_guarded_pairing(loop_var: Optional[str], excluded_var: Optional[str]) -> bool:
        return loop_var is not None and loop_var == excluded_var

    @property
    def has_pattern(self) -> bool:
        return any(
            super_ln > cond_ln and not self._is_guarded_pairing(loop_var, excluded_var)
            for cond_ln, _, loop_var in self.non_returning_conditionals
            for super_ln, excluded_var in self.unconditional_super_calls
        )

    def get_matching_conditions(self) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for cond_ln, cond_text, loop_var in self.non_returning_conditionals:
            genuinely_unguarded = any(
                super_ln > cond_ln and not self._is_guarded_pairing(loop_var, excluded_var)
                for super_ln, excluded_var in self.unconditional_super_calls
            )
            if genuinely_unguarded and cond_text not in seen:
                seen.add(cond_text)
                ordered.append(cond_text)
        return ordered


UNGUARDED_SUPER_WARNING_TEMPLATE = (
    "SUPER() NON GARD\u00c9: '{method_name}' (module '{module}') contient une "
    "branche conditionnelle (`{condition}`) qui modifie l'\u00e9tat sans `return` "
    "explicite, suivie d'un appel `super().{method_name}(...)` inconditionnel plus "
    "loin dans la m\u00e9thode. La logique de la classe parente va se r\u00e9appliquer sur "
    "TOUS les enregistrements, y compris ceux couverts par cette condition -- "
    "risque r\u00e9el qu'elle soit silencieusement annul\u00e9e. "
    "[Confiance: FAIBLE -- heuristique statique sur la forme exacte du contr\u00f4le de "
    "flux, ne d\u00e9tecte pas les gardes formul\u00e9es autrement]"
)


def detect_unguarded_super(
    source: str, filepath: str, method_name: str, target_lineno: int, module: str = ""
) -> Optional[str]:
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as e:
        _logger.warning("Could not parse %s for override-chain analysis: %s", filepath, e)
        return None

    target_func = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == method_name
            and node.lineno == target_lineno
        ):
            target_func = node
            break

    if target_func is None:
        return None

    visitor = _UnguardedSuperVisitor(method_name)
    for stmt in target_func.body:
        visitor.visit(stmt)

    if visitor.has_pattern:
        conditions = visitor.get_matching_conditions()
        condition_text = " / ".join(conditions) if conditions else "?"
        return UNGUARDED_SUPER_WARNING_TEMPLATE.format(
            method_name=method_name, module=module or "?", condition=condition_text
        )
    return None
