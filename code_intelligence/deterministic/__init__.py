"""
code_intelligence/deterministic

Deterministic graph query engines and evaluators for Odoo Code Intelligence.
"""

from code_intelligence.deterministic.access_evaluator import (
    AccessEvaluationResult,
    who_has_access_to,
)
from code_intelligence.deterministic.button_path import (
    button_execution_path,
)
from code_intelligence.deterministic.button_path_models import (
    ButtonExecutionPathResult,
)
from code_intelligence.deterministic.common import (
    NOT_FOUND_MARKER,
    QueryStatus,
)
from code_intelligence.deterministic.domain_evaluator import (
    _kleene_and,
    _kleene_not,
    _kleene_or,
    evaluate_domain_force,
)
from code_intelligence.deterministic.domain_parser import (
    _DomainParseError,
    _DynamicRef,
    _normalize_domain_tokens,
    _parse_domain_ast,
)
from code_intelligence.deterministic.field_impact import (
    FieldImpactResult,
    field_change_impact,
)
from code_intelligence.deterministic.group_resolver import (
    FUZZY_GROUP_MATCH_THRESHOLD,
    _expand_implied_user_groups,
    _expand_inheriting_acl_groups,
    _fold_accents,
    _group_display_name,
    _group_fuzzy_matches_display_name,
    _group_short_name,
    _strip_group_prefix,
    resolve_group_identifier,
)
from code_intelligence.deterministic.inheritance_chain import (
    InheritanceChainResult,
    trace_full_inheritance,
)
from code_intelligence.deterministic.record_rules import (
    evaluate_record_rules,
)
from code_intelligence.deterministic.record_rules_models import (
    RuleDetail,
    RuleEvaluationResult,
)
from code_intelligence.deterministic.workflow_process import (
    WorkflowProcessResult,
    describe_workflow,
)

__all__ = [
    "NOT_FOUND_MARKER",
    "QueryStatus",
    "_DomainParseError",
    "_DynamicRef",
    "_parse_domain_ast",
    "_normalize_domain_tokens",
    "_kleene_and",
    "_kleene_or",
    "_kleene_not",
    "evaluate_domain_force",
    "FUZZY_GROUP_MATCH_THRESHOLD",
    "_group_short_name",
    "_group_display_name",
    "_strip_group_prefix",
    "_fold_accents",
    "_group_fuzzy_matches_display_name",
    "resolve_group_identifier",
    "_expand_implied_user_groups",
    "_expand_inheriting_acl_groups",
    "RuleDetail",
    "RuleEvaluationResult",
    "evaluate_record_rules",
    "AccessEvaluationResult",
    "who_has_access_to",
    "FieldImpactResult",
    "field_change_impact",
    "ButtonExecutionPathResult",
    "button_execution_path",
    "InheritanceChainResult",
    "trace_full_inheritance",
    "WorkflowProcessResult",
    "describe_workflow",
]
