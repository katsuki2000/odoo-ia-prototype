"""
code_intelligence/semgrep_locks_analyzer.py

Stories S2.5 & S2.6: Security lock & dynamic uncertainty analysis for Python code.
  - S2.5: Detects hardcoded email/login lists and exact UserError/ValidationError exception strings.
  - S2.6: Detects dynamic dispatch (getattr, eval, exec) and marks results with confidence='low'.

Facade module maintaining full backward compatibility.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple

from code_intelligence.knowledge_rules.security.evidence import (
    build_security_lock_evidence,
    extract_method_security_constraints,
    format_security_locks_summary,
)
from code_intelligence.knowledge_rules.security.visitor import (
    _EMAIL_PATTERN,
    _EVAL_PATTERN,
    _EXCEPTION_RAISE_PATTERN,
    _EXEC_PATTERN,
    _GETATTR_PATTERN,
    _HAS_GROUP_PATTERN,
    SecurityLockASTVisitor,
)
from core.evidence import Evidence
from core.confidence_tags import confidence_label

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
