"""
Security Lock AST & Constraint Analysis Subpackage.
"""

from code_intelligence.knowledge_rules.security.analyzer import (
    PythonSecurityLockAnalysis,
    analyze_python_security_locks,
    python_source_has_security_findings,
)
from code_intelligence.knowledge_rules.security.evidence import (
    build_security_lock_evidence,
    extract_method_security_constraints,
    format_security_locks_summary,
)
from code_intelligence.knowledge_rules.security.visitor import (
    SecurityLockASTVisitor,
    _EMAIL_PATTERN,
    _EVAL_PATTERN,
    _EXEC_PATTERN,
    _GETATTR_PATTERN,
    _EXCEPTION_RAISE_PATTERN,
    _HAS_GROUP_PATTERN,
)
from code_intelligence.knowledge_rules.security.locks import (
    _amount_present_in_text,
    _extract_security_lock_condition_amounts,
    _correct_security_lock_threshold_contradictions,
    _backfill_missing_security_lock_amount,
    _SECURITY_LOCK_MESSAGES_MARKER,
    _OVERRIDE_CHAIN_AMOUNT_RE,
)
from code_intelligence.knowledge_rules.security.gate import (
    OmittedItem,
    gate_observation,
    _has_elevated_access,
    _find_elevating_group,
    _extract_has_group_xmlids_from_source,
    _expand_user_groups_ordered,
    _redact_sensitive_bypass_lines,
    _OMITTED_MARKER,
    _HAS_GROUP_SOURCE_PATTERN,
)

__all__ = [
    "PythonSecurityLockAnalysis",
    "analyze_python_security_locks",
    "python_source_has_security_findings",
    "build_security_lock_evidence",
    "extract_method_security_constraints",
    "format_security_locks_summary",
    "SecurityLockASTVisitor",
    "_EMAIL_PATTERN",
    "_EVAL_PATTERN",
    "_EXEC_PATTERN",
    "_GETATTR_PATTERN",
    "_EXCEPTION_RAISE_PATTERN",
    "_HAS_GROUP_PATTERN",
    "_amount_present_in_text",
    "_extract_security_lock_condition_amounts",
    "_correct_security_lock_threshold_contradictions",
    "_backfill_missing_security_lock_amount",
    "_SECURITY_LOCK_MESSAGES_MARKER",
    "_OVERRIDE_CHAIN_AMOUNT_RE",
    "OmittedItem",
    "gate_observation",
    "_has_elevated_access",
    "_find_elevating_group",
    "_extract_has_group_xmlids_from_source",
    "_expand_user_groups_ordered",
    "_redact_sensitive_bypass_lines",
    "_OMITTED_MARKER",
    "_HAS_GROUP_SOURCE_PATTERN",
]
