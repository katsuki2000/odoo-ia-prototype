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
_USER_HAS_GROUPS_PATTERN = re.compile(r"user_has_groups\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")


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
        self.required_group_is_gating: List[bool] = []
        # todo/contexte.txt, session "SecurityLockASTVisitor BoolOp/Or gap"
        # (PUR-Q1 rejeu, purchase.order._approval_allowed): required_group_
        # is_gating only distinguishes if/raise gates from message-selection-
        # only ifs (section 825) -- it has no concept of a bare `return (A or
        # B or has_group(...))` boolean expression, which is neither. When a
        # has_group()/user_has_groups() call is one disjunct of an `or` whose
        # OTHER disjuncts are unrelated to any group check, the group is NOT
        # a hard requirement -- any of those other conditions independently
        # satisfies the expression. required_group_alt_conditions carries the
        # unparsed text of those other disjuncts (joined by ' OU '), index-
        # aligned with required_groups; "" means no such alternative exists
        # (the normal, unconditional-requirement case, unchanged).
        self.required_group_alt_conditions: List[str] = []
        self._or_alt_stack: List[List[str]] = []
        self.static_filters: List[Tuple[str, str, int, int]] = []
        self._if_test_stack: List[ast.expr] = []
        self._function_stack: List[str] = []
        self._local_var_defs: List[Dict[str, ast.expr]] = []
        # section 825 (ACC-Q2, account.move._check_fiscalyear_lock_date):
        # gating_stack[-1] is True iff the innermost enclosing `if` we are
        # currently inside has a Raise(ValidationError/UserError/...) node
        # somewhere in ITS OWN body/orelse -- i.e. this `if`'s condition
        # actually determines whether the raise fires. A has_group()/
        # user_has_groups() call found while gating_stack[-1] is False sits
        # inside an `if` that only builds/selects an error MESSAGE STRING
        # (assignments only), with the actual `raise` happening later,
        # unconditionally, as a sibling statement outside that `if` -- the
        # group check does not gate whether the action is blocked at all.
        self._gating_stack: List[bool] = []

    def visit_If(self, node: ast.If):
        self._if_test_stack.append(node.test)
        has_raise_in_branches = any(
            isinstance(n, ast.Raise)
            for stmt in (node.body + node.orelse)
            for n in ast.walk(stmt)
        )
        self._gating_stack.append(has_raise_in_branches)
        self.generic_visit(node)
        self._gating_stack.pop()
        self._if_test_stack.pop()

    def visit_BoolOp(self, node: ast.BoolOp):
        if not isinstance(node.op, ast.Or):
            # Only `or` expressions can hide an unconditional-looking
            # has_group() behind an unrelated, independently-sufficient
            # alternative. `and` (or any other BoolOp) means every operand,
            # group check included, is still genuinely required -- leave
            # _or_alt_stack untouched so a has_group() nested under an
            # `and` still inherits the nearest enclosing `or`'s alternatives
            # (if any), rather than being told it has none.
            self.generic_visit(node)
            return

        alt_conditions: List[str] = []
        for value in node.values:
            contains_group_check = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("has_group", "user_has_groups")
                for n in ast.walk(value)
            )
            if not contains_group_check:
                try:
                    alt_conditions.append(ast.unparse(self._resolve_local_names(value)))
                except Exception:
                    alt_conditions.append("?")

        self._or_alt_stack.append(alt_conditions)
        self.generic_visit(node)
        self._or_alt_stack.pop()

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
        if isinstance(node, ast.Name):
            # raise UserError(message) where `message` was built a few lines
            # above, as in account.move::_check_fiscalyear_lock_date. Without
            # this the whole lock disappears from the analysis (contexte 816).
            local_map = self._local_var_defs[-1] if self._local_var_defs else {}
            assigned = local_map.get(node.id)
            if assigned is not None and not isinstance(assigned, ast.Name):
                return self._extract_exception_str(assigned)
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
                    self.required_group_is_gating.append(
                        self._gating_stack[-1] if self._gating_stack else True
                    )
                    alt = self._or_alt_stack[-1] if self._or_alt_stack else []
                    self.required_group_alt_conditions.append(" OU ".join(alt))

        if isinstance(node.func, ast.Attribute) and node.func.attr == "user_has_groups":
            # user_has_groups(groups) takes ONE comma-separated string arg,
            # e.g. 'account.group_account_manager,base.group_system', with
            # optional '!' negation prefixes -- a distinct Odoo idiom from
            # has_group(single_xmlid) that the extractor previously missed
            # entirely (todo/contexte.txt 816, account.move lock date case).
            # Folded into the same required_groups/has_group format: for the
            # grounding contract (access_guards.py::_extract_required_groups,
            # security_evidence.py's 'Groupe(s) ... (has_group):' line) both
            # are the same category of self-service group-membership check.
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                for part in node.args[0].value.split(","):
                    group_xmlid = part.strip().lstrip("!")
                    if group_xmlid and group_xmlid not in self.required_groups:
                        self.required_groups.append(group_xmlid)
                        self.required_group_methods.append(self._current_method_name())
                        self.required_group_linenos.append(node.lineno)
                        self.required_group_is_gating.append(
                            self._gating_stack[-1] if self._gating_stack else True
                        )
                        alt = self._or_alt_stack[-1] if self._or_alt_stack else []
                        self.required_group_alt_conditions.append(" OU ".join(alt))

        if isinstance(node.func, ast.Attribute) and node.func.attr == "ref":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                val = node.args[0].value
                if "group" in val:
                    group_xmlid = val
                    if group_xmlid not in self.required_groups:
                        self.required_groups.append(group_xmlid)
                        self.required_group_methods.append(self._current_method_name())
                        self.required_group_linenos.append(node.lineno)
                        self.required_group_is_gating.append(True)
                        self.required_group_alt_conditions.append("")

        self.generic_visit(node)

# ── Security Analyzer ────────────────────────────────────────────────────

"""
code_intelligence/semgrep_locks_analyzer.py

Stories S2.5 & S2.6: Security lock & dynamic uncertainty analysis for Python code.
  - S2.5: Detects hardcoded email/login lists and exact UserError/ValidationError exception strings.
  - S2.6: Detects dynamic dispatch (getattr, eval, exec) and marks results with confidence='low'.

Facade module maintaining full backward compatibility.
"""


import ast
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple

from code_intelligence.rules.security_evidence import (
    build_security_lock_evidence,
    extract_method_security_constraints,
    format_security_locks_summary,
)
from code_intelligence.rules.security import (
    _EMAIL_PATTERN,
    _EVAL_PATTERN,
    _EXCEPTION_RAISE_PATTERN,
    _EXEC_PATTERN,
    _GETATTR_PATTERN,
    _HAS_GROUP_PATTERN,
    _USER_HAS_GROUPS_PATTERN,
    SecurityLockASTVisitor,
)
from core.evidence.evidence import Evidence
from core.output import confidence_label

_logger = logging.getLogger(__name__)


@dataclass
class PythonSecurityLockAnalysis:
    """Result of analyzing Python model code for security locks and uncertainties."""
    filepath: str
    has_hardcoded_logins: bool = False
    hardcoded_logins: List[str] = field(default_factory=list)
    exception_messages: List[str] = field(default_factory=list)
    exception_conditions: List[str] = field(default_factory=list)
    exception_guard_fields: List[str] = field(default_factory=list)
    exception_linenos: List[int] = field(default_factory=list)
    has_dynamic_dispatch: bool = False
    dynamic_dispatch_types: List[str] = field(default_factory=list)
    required_groups: List[str] = field(default_factory=list)
    required_group_methods: List[str] = field(default_factory=list)
    required_group_linenos: List[int] = field(default_factory=list)
    required_group_is_gating: List[bool] = field(default_factory=list)
    required_group_alt_conditions: List[str] = field(default_factory=list)
    static_filters: List[Tuple[str, str, int, int]] = field(default_factory=list)
    security_warnings: List[str] = field(default_factory=list)
    confidence: str = "high"
    summary_text: str = ""
    evidence: List[Evidence] = field(default_factory=list)


def analyze_python_security_locks(code: str, filepath: str) -> PythonSecurityLockAnalysis:
    """
    Analyze Python source code for hardcoded security locks, exception messages,
    and dynamic dispatch uncertainties.
    """
    result = PythonSecurityLockAnalysis(filepath=filepath)

    if not code or not code.strip():
        result.summary_text = f"File '{filepath}': Empty code."
        result.evidence = build_security_lock_evidence(
            filepath,
            hardcoded_logins=[],
            exception_messages=[],
            exception_conditions=[],
            exception_guard_fields=[],
            exception_linenos=[],
            required_groups=[],
            required_group_methods=[],
            required_group_linenos=[],
            dynamic_dispatch_types=[],
        )
        return result

    # 1. AST Parsing
    try:
        tree = ast.parse(code, filename=filepath)
        visitor = SecurityLockASTVisitor(filepath)
        visitor.visit(tree)

        result.hardcoded_logins = visitor.hardcoded_logins
        result.exception_messages = visitor.exception_messages
        result.exception_conditions = visitor.exception_conditions
        result.exception_guard_fields = visitor.exception_guard_fields
        result.exception_linenos = visitor.exception_linenos
        result.dynamic_dispatch_types = visitor.dynamic_dispatches
        result.required_groups = visitor.required_groups
        result.required_group_methods = visitor.required_group_methods
        result.required_group_linenos = visitor.required_group_linenos
        result.required_group_is_gating = visitor.required_group_is_gating
        result.required_group_alt_conditions = visitor.required_group_alt_conditions
        result.static_filters = visitor.static_filters

    except SyntaxError:
        _logger.warning("AST parse failed for %s, falling back to regex analysis", filepath)

    # 2. Regex fallback / reinforcement
    if not result.hardcoded_logins:
        emails = _EMAIL_PATTERN.findall(code)
        if emails:
            seen = set()
            for e in emails:
                if e not in seen:
                    seen.add(e)
                    result.hardcoded_logins.append(e)

    if not result.dynamic_dispatch_types:
        for pattern, name in [(_GETATTR_PATTERN, "getattr"), (_EVAL_PATTERN, "eval"), (_EXEC_PATTERN, "exec")]:
            if pattern.search(code):
                result.dynamic_dispatch_types.append(name)

    if not result.exception_messages:
        for match in _EXCEPTION_RAISE_PATTERN.finditer(code):
            raw_msg = match.group(1).strip("'\"")
            if raw_msg and raw_msg not in result.exception_messages:
                result.exception_messages.append(raw_msg)
                result.exception_conditions.append("")
                result.exception_guard_fields.append("")
                result.exception_linenos.append(0)

    if not result.required_groups:
        for group_xmlid in _HAS_GROUP_PATTERN.findall(code):
            if group_xmlid not in result.required_groups:
                result.required_groups.append(group_xmlid)
                result.required_group_methods.append("")
                result.required_group_linenos.append(0)
                # Regex fallback has no AST/control-flow information to
                # determine gating (section 825) -- default to True (the
                # pre-825 behavior) rather than assert a claim we can't verify.
                result.required_group_is_gating.append(True)
                # Same reasoning for the BoolOp/Or alternative-conditions
                # signal: no AST means no way to detect an enclosing `or`,
                # so this must stay "" rather than silently misalign with
                # required_groups or assert an alternative we never saw.
                result.required_group_alt_conditions.append("")
        for groups_arg in _USER_HAS_GROUPS_PATTERN.findall(code):
            for part in groups_arg.split(","):
                group_xmlid = part.strip().lstrip("!")
                if group_xmlid and group_xmlid not in result.required_groups:
                    result.required_groups.append(group_xmlid)
                    result.required_group_methods.append("")
                    result.required_group_linenos.append(0)
                    result.required_group_is_gating.append(True)
                    result.required_group_alt_conditions.append("")

    result.evidence = build_security_lock_evidence(
        filepath,
        hardcoded_logins=result.hardcoded_logins,
        exception_messages=result.exception_messages,
        exception_conditions=result.exception_conditions,
        exception_guard_fields=result.exception_guard_fields,
        exception_linenos=result.exception_linenos,
        required_groups=result.required_groups,
        required_group_methods=result.required_group_methods,
        required_group_linenos=result.required_group_linenos,
        required_group_is_gating=result.required_group_is_gating,
        required_group_alt_conditions=result.required_group_alt_conditions,
        dynamic_dispatch_types=result.dynamic_dispatch_types,
    )

    # 3. Categorize findings
    if result.hardcoded_logins:
        result.has_hardcoded_logins = True
        result.security_warnings.append(
            f" LOGINS/EMAILS EN DUR: Fichier '{filepath}' contient des adresses privilégies "
            f"codées en dur: {result.hardcoded_logins}. Contourne le système de droits standard Odoo."
        )

    if result.dynamic_dispatch_types:
        result.has_dynamic_dispatch = True
        result.confidence = "low"
        result.security_warnings.append(
            f" DISPATCH DYNAMIQUE: Fichier '{filepath}' utilise {', '.join(result.dynamic_dispatch_types)}(). "
            f"La logique d'exécution exacte dépend de paramètres dynamiques et ne peut pas être "
            f"classifiée statiquement avec certitude. [Confiance: {confidence_label(result.confidence)}]"
        )

    # 4. Summary Text
    result.summary_text = format_security_locks_summary(result, code, filepath)
    return result


def python_source_has_security_findings(code: str, filepath: str = "<unknown>") -> bool:
    """
    Checks if the Python code has any security findings:
    hardcoded logins/emails, exception messages, dynamic dispatch, required groups, or static exclusion filters.
    """
    result = analyze_python_security_locks(code, filepath)
    return bool(
        result.hardcoded_logins
        or result.exception_messages
        or result.dynamic_dispatch_types
        or result.required_groups
        or result.static_filters
    )


# Backward compatibility re-export
_build_security_lock_evidence = build_security_lock_evidence

__all__ = [
    "PythonSecurityLockAnalysis",
    "SecurityLockASTVisitor",
    "analyze_python_security_locks",
    "python_source_has_security_findings",
    "extract_method_security_constraints",
    "_build_security_lock_evidence",
    "build_security_lock_evidence",
    "format_security_locks_summary",
    "_EMAIL_PATTERN",
    "_GETATTR_PATTERN",
    "_EVAL_PATTERN",
    "_EXEC_PATTERN",
    "_EXCEPTION_RAISE_PATTERN",
    "_HAS_GROUP_PATTERN",
]
