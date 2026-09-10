"""
code_intelligence/semgrep_locks_visitor.py

AST visitor for detecting security locks, exception raises, dynamic dispatch,
and required Odoo security groups.
"""

from __future__ import annotations

import ast
import copy
import re
from typing import Any, Dict, List, Optional, Tuple

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_GETATTR_PATTERN = re.compile(r"\bgetattr\s*\(")
_EVAL_PATTERN = re.compile(r"\beval\s*\(")
_EXEC_PATTERN = re.compile(r"\bexec\s*\(")
_EXCEPTION_RAISE_PATTERN = re.compile(r"raise\s+(?:ValidationError|UserError)\s*\(\s*([\"'].*?[\"'])", re.DOTALL)
_HAS_GROUP_PATTERN = re.compile(r"has_group\s*\(\s*['\"]([\w.]+)['\"]\s*\)")


class SecurityLockASTVisitor(ast.NodeVisitor):
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.hardcoded_logins: List[str] = []
        self.exception_messages: List[str] = []
        self.exception_conditions: List[str] = []
        self.exception_guard_fields: List[str] = []
        self.exception_linenos: List[int] = []
        self.dynamic_dispatches: List[str] = []
        self.required_groups: List[str] = []
        self.required_group_methods: List[str] = []
        self.required_group_linenos: List[int] = []
        self.static_filters: List[Tuple[str, str, int, int]] = []
        self._if_test_stack: List[ast.expr] = []
        self._function_stack: List[str] = []
        self._local_var_defs: List[Dict[str, ast.expr]] = []

    def visit_If(self, node: ast.If):
        self._if_test_stack.append(node.test)
        self.generic_visit(node)
        self._if_test_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._function_stack.append(node.name)
        self._local_var_defs.append({})
        self.generic_visit(node)
        self._local_var_defs.pop()
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._function_stack.append(node.name)
        self._local_var_defs.append({})
        self.generic_visit(node)
        self._local_var_defs.pop()
        self._function_stack.pop()

    def _current_method_name(self) -> str:
        return self._function_stack[-1] if self._function_stack else ""

    def _resolve_local_names(self, node: ast.expr) -> ast.expr:
        if not self._local_var_defs:
            return node
        local_map = self._local_var_defs[-1]
        if not local_map:
            return node

        class _NameResolver(ast.NodeTransformer):
            def visit_Name(inner_self, n: ast.Name):
                if isinstance(n.ctx, ast.Load) and n.id in local_map:
                    return copy.deepcopy(local_map[n.id])
                return n

        return _NameResolver().visit(copy.deepcopy(node))

    def _current_condition_text(self) -> str:
        if not self._if_test_stack:
            return ""
        parts = []
        for test in self._if_test_stack:
            try:
                parts.append(ast.unparse(self._resolve_local_names(test)))
            except Exception:
                parts.append("?")
        return " and ".join(parts)

    def _detect_link_guard_field(self) -> str:
        for test in self._if_test_stack:
            if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) and test.values:
                first = test.values[0]
                if not isinstance(first, ast.Compare):
                    try:
                        return ast.unparse(first)
                    except Exception:
                        return ""
            elif isinstance(test, (ast.Attribute, ast.Name)):
                try:
                    return ast.unparse(test)
                except Exception:
                    return ""
        return ""

    def visit_Assign(self, node: ast.Assign):
        if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            str_elts = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    str_elts.append(elt.value)

            emails = [s for s in str_elts if _EMAIL_PATTERN.match(s)]
            if emails:
                self.hardcoded_logins.extend(emails)

        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                name_lower = name.lower()
                if any(k in name_lower for k in ("blacklist", "whitelist", "exclude", "excluded", "sensitive")):
                    try:
                        val = ast.literal_eval(node.value)
                    except Exception:
                        try:
                            val = ast.unparse(node.value)
                        except Exception:
                            val = "..."
                    start_l = node.lineno
                    end_l = getattr(node, "end_lineno", start_l)
                    self.static_filters.append((name, str(val), start_l, end_l))

        if (
            self._local_var_defs
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            self._local_var_defs[-1][node.targets[0].id] = node.value

        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise):
        func_name = ""
        if isinstance(node.exc, ast.Call):
            if isinstance(node.exc.func, ast.Name):
                func_name = node.exc.func.id
            elif isinstance(node.exc.func, ast.Attribute):
                func_name = node.exc.func.attr
        elif isinstance(node.exc, ast.Name):
            func_name = node.exc.id
        elif isinstance(node.exc, ast.Attribute):
            func_name = node.exc.attr

        if func_name in {"ValidationError", "UserError", "AccessDenied", "AccessError"}:
            message = (
                self._extract_exception_str(node.exc.args[0])
                if (isinstance(node.exc, ast.Call) and node.exc.args)
                else func_name
            )

            if message is not None:
                self.exception_messages.append(message)
                self.exception_conditions.append(self._current_condition_text())
                self.exception_guard_fields.append(self._detect_link_guard_field())
                self.exception_linenos.append(node.lineno)

        self.generic_visit(node)

    def _extract_exception_str(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.strip()
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Name) and node.func.id == "_") or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "_"
            ):
                if node.args:
                    return self._extract_exception_str(node.args[0])
        if isinstance(node, ast.BinOp):
            return self._extract_exception_str(node.left)
        if isinstance(node, ast.JoinedStr):
            parts = [
                p.value
                for p in node.values
                if isinstance(p, ast.Constant) and isinstance(p.value, str)
            ]
            if parts:
                return "".join(parts).strip()
        return None

    def visit_Call(self, node: ast.Call):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name in {"getattr", "eval", "exec"}:
            if func_name not in self.dynamic_dispatches:
                self.dynamic_dispatches.append(func_name)

        if isinstance(node.func, ast.Attribute) and node.func.attr == "has_group":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                group_xmlid = node.args[0].value
                if group_xmlid not in self.required_groups:
                    self.required_groups.append(group_xmlid)
                    self.required_group_methods.append(self._current_method_name())
                    self.required_group_linenos.append(node.lineno)

        if isinstance(node.func, ast.Attribute) and node.func.attr == "ref":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                val = node.args[0].value
                if "group" in val:
                    group_xmlid = val
                    if group_xmlid not in self.required_groups:
                        self.required_groups.append(group_xmlid)
                        self.required_group_methods.append(self._current_method_name())
                        self.required_group_linenos.append(node.lineno)

        self.generic_visit(node)
