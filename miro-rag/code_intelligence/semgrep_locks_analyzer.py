"""
code_intelligence/semgrep_locks_analyzer.py

Stories S2.5 & S2.6: Security lock & dynamic uncertainty analysis for Python code.
  - S2.5: Detects hardcoded email/login lists (e.g. _VALIDATEURS_EXCEPTIONNELS) and exact UserError/ValidationError exception strings.
  - S2.6: Detects dynamic dispatch (getattr, eval, exec) and marks results with confidence='low'.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Set, Optional

import logging

_logger = logging.getLogger(__name__)


@dataclass
class PythonSecurityLockAnalysis:
    """Result of analyzing Python model code for security locks and uncertainties."""
    filepath: str
    has_hardcoded_logins: bool = False
    hardcoded_logins: List[str] = field(default_factory=list)
    exception_messages: List[str] = field(default_factory=list)
    has_dynamic_dispatch: bool = False
    dynamic_dispatch_types: List[str] = field(default_factory=list)
    security_warnings: List[str] = field(default_factory=list)
    confidence: str = "high"
    summary_text: str = ""


# Regex fallback for email pattern detection
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_GETATTR_PATTERN = re.compile(r"\bgetattr\s*\(")
_EVAL_PATTERN = re.compile(r"\beval\s*\(")
_EXEC_PATTERN = re.compile(r"\bexec\s*\(")
_EXCEPTION_RAISE_PATTERN = re.compile(r"raise\s+(?:ValidationError|UserError)\s*\(\s*([\"'].*?[\"'])", re.DOTALL)


class SecurityLockASTVisitor(ast.NodeVisitor):
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.hardcoded_logins: List[str] = []
        self.exception_messages: List[str] = []
        self.dynamic_dispatches: List[str] = []

    def visit_Assign(self, node: ast.Assign):
        """Detect hardcoded email/login lists assigned to variables like _VALIDATEURS_EXCEPTIONNELS."""
        # Check if right-hand side is a List/Tuple of string literals
        if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            str_elts = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    str_elts.append(elt.value)

            # Check if elements contain emails
            emails = [s for s in str_elts if _EMAIL_PATTERN.match(s)]
            if emails:
                self.hardcoded_logins.extend(emails)

        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise):
        """Extract exact UserError and ValidationError exception message strings."""
        if isinstance(node.exc, ast.Call):
            func_name = ""
            if isinstance(node.exc.func, ast.Name):
                func_name = node.exc.func.id
            elif isinstance(node.exc.func, ast.Attribute):
                func_name = node.exc.func.attr

            if func_name in {"ValidationError", "UserError"}:
                if node.exc.args:
                    first_arg = node.exc.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        self.exception_messages.append(first_arg.value.strip())
                    elif isinstance(first_arg, ast.BinOp) and isinstance(first_arg.left, ast.Constant):
                        # e.g. "Msg %s" % var -> extract template
                        if isinstance(first_arg.left.value, str):
                            self.exception_messages.append(first_arg.left.value.strip())
                    elif isinstance(first_arg, ast.JoinedStr):
                        # f-string -> extract literal text parts
                        parts = [p.value for p in first_arg.values if isinstance(p, ast.Constant) and isinstance(p.value, str)]
                        if parts:
                            self.exception_messages.append("".join(parts).strip())

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Detect dynamic dispatch calls: getattr, eval, exec."""
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name in {"getattr", "eval", "exec"}:
            if func_name not in self.dynamic_dispatches:
                self.dynamic_dispatches.append(func_name)

        self.generic_visit(node)


def analyze_python_security_locks(code: str, filepath: str) -> PythonSecurityLockAnalysis:
    """
    Analyze Python source code for hardcoded security locks, exception messages,
    and dynamic dispatch uncertainties.
    """
    result = PythonSecurityLockAnalysis(filepath=filepath)

    if not code or not code.strip():
        result.summary_text = f"File '{filepath}': Empty code."
        return result

    # 1. AST Parsing
    try:
        tree = ast.parse(code, filename=filepath)
        visitor = SecurityLockASTVisitor(filepath)
        visitor.visit(tree)

        result.hardcoded_logins = visitor.hardcoded_logins
        result.exception_messages = visitor.exception_messages
        result.dynamic_dispatch_types = visitor.dynamic_dispatches

    except SyntaxError:
        _logger.warning("AST parse failed for %s, falling back to regex analysis", filepath)

    # 2. Regex fallback / reinforcement
    if not result.hardcoded_logins:
        emails = _EMAIL_PATTERN.findall(code)
        if emails:
            # Filter unique emails
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

    # 3. Categorize findings
    if result.hardcoded_logins:
        result.has_hardcoded_logins = True
        result.security_warnings.append(
            f"⚠️ LOGINS/EMAILS EN DUR: Fichier '{filepath}' contient des adresses privilégies "
            f"codées en dur: {result.hardcoded_logins}. Contourne le système de droits standard Odoo."
        )

    if result.dynamic_dispatch_types:
        result.has_dynamic_dispatch = True
        result.confidence = "low"
        result.security_warnings.append(
            f"⚠️ DISPATCH DYNAMIQUE: Fichier '{filepath}' utilise {', '.join(result.dynamic_dispatch_types)}(). "
            f"La logique d'exécution exacte dépend de paramètres dynamiques et ne peut pas être "
            f"classifiée statiquement avec certitude. [Confiance: FAIBLE]"
        )

    # 4. Summary Text
    from code_intelligence.utils import format_file_link, SENSITIVE_BYPASS_MARKER
    line_count = max(1, len(code.splitlines()))
    file_link = format_file_link(filepath, 1, line_count)
    lines = [f"Analyse des verrous Python ({file_link}) [Confiance: {result.confidence.upper()}]:"]
    if result.has_hardcoded_logins:
        # Bloc 7 (J23-24, revised): the ONLY line in this analyzer's output
        # that describes an actual bypass (privileged access granted
        # outside Odoo's normal ir.rule/ACL system) rather than ordinary
        # governance/uncertainty info -- marked so authorization_gate.py
        # redacts just this line for unprivileged requesters, not the
        # whole analysis (which also covers legitimate approval-flow
        # questions that must stay answerable for everyone).
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilégies en dur: {result.hardcoded_logins}")
    if result.exception_messages:
        lines.append(f"  - Messages de verrous (UserError/ValidationError):")
        for msg in result.exception_messages:
            lines.append(f"    * \"{msg}\"")
    if result.has_dynamic_dispatch:
        lines.append(f"  - Incertitude dynamique ({', '.join(result.dynamic_dispatch_types)}): revue manuelle recommandée")

    if not result.security_warnings and not result.exception_messages:
        lines.append("  - Aucun verrou spécifique ni incertitude dynamique détecté.")

    result.summary_text = "\n".join(lines)
    return result
