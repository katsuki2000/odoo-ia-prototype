"""
code_intelligence/deterministic_tools.py

Specialized Deterministic Graph Query Tools for Odoo Code Intelligence.
Provides tools for access evaluation, field impact analysis, button execution paths,
and ir.rule evaluation.

NOTE: This module serves as a backward-compatible facade re-exporting all components
from the modular package `code_intelligence.deterministic`.
"""

from code_intelligence.deterministic.access_evaluator import (
    AccessEvaluationResult,
    _build_access_evidence,
    _eval_single_permission,
    who_has_access_to,
)
from code_intelligence.deterministic.button_path import (
    _requester_satisfies_required_groups,
    button_execution_path,
)
from code_intelligence.deterministic.button_path_models import (
    ButtonExecutionPathResult,
    _build_button_execution_evidence,
)
from code_intelligence.deterministic.common import (
    NOT_FOUND_MARKER,
    QueryStatus,
)
from code_intelligence.deterministic.domain_evaluator import (
    _evaluate_domain_tokens,
    _evaluate_leaf,
    _kleene_and,
    _kleene_not,
    _kleene_or,
    _resolve_dynamic_ref,
    _resolve_leaf_value,
    evaluate_domain_force,
)
from code_intelligence.deterministic.domain_parser import (
    _DOMAIN_COMPARISON_OPS,
    _DOMAIN_LOGICAL_OPS,
    _DomainParseError,
    _DynamicRef,
    _domain_ast_field,
    _domain_ast_op,
    _domain_ast_to_token,
    _domain_ast_value,
    _normalize_domain_tokens,
    _parse_domain_ast,
)
from code_intelligence.deterministic.field_impact import (
    FieldImpactResult,
    _bfs_downstream,
    _build_field_impact_evidence,
    _collect_upstream_triggers,
    _field_to_short_name,
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
    _build_inheritance_evidence,
    trace_full_inheritance,
)
from code_intelligence.deterministic.record_rules import (
    _build_record_rules_evidence,
    evaluate_record_rules,
)
from code_intelligence.deterministic.record_rules_models import (
    RuleDetail,
    RuleEvaluationResult,
)
from code_intelligence.deterministic.workflow_process import (
    WorkflowProcessResult,
    _build_workflow_evidence,
    describe_workflow,
)
from code_intelligence.deterministic.xml_view_finder import (
    _find_field_in_xml_views,
)

__all__ = [
    "NOT_FOUND_MARKER",
    "QueryStatus",
    "_DOMAIN_COMPARISON_OPS",
    "_DOMAIN_LOGICAL_OPS",
    "_DomainParseError",
    "_DynamicRef",
    "_domain_ast_op",
    "_domain_ast_field",
    "_domain_ast_value",
    "_domain_ast_to_token",
    "_parse_domain_ast",
    "_normalize_domain_tokens",
    "_resolve_dynamic_ref",
    "_resolve_leaf_value",
    "_evaluate_leaf",
    "_kleene_and",
    "_kleene_or",
    "_kleene_not",
    "_evaluate_domain_tokens",
    "evaluate_domain_force",
    "RuleDetail",
    "RuleEvaluationResult",
    "FUZZY_GROUP_MATCH_THRESHOLD",
    "_group_short_name",
    "_group_display_name",
    "_strip_group_prefix",
    "_fold_accents",
    "_group_fuzzy_matches_display_name",
    "resolve_group_identifier",
    "_build_record_rules_evidence",
    "evaluate_record_rules",
    "AccessEvaluationResult",
    "_build_access_evidence",
    "_eval_single_permission",
    "who_has_access_to",
    "FieldImpactResult",
    "_field_to_short_name",
    "_bfs_downstream",
    "_collect_upstream_triggers",
    "_build_field_impact_evidence",
    "field_change_impact",
    "ButtonExecutionPathResult",
    "_requester_satisfies_required_groups",
    "_build_button_execution_evidence",
    "_find_field_in_xml_views",
    "button_execution_path",
    "InheritanceChainResult",
    "WorkflowProcessResult",
    "_build_workflow_evidence",
    "_build_inheritance_evidence",
    "trace_full_inheritance",
    "describe_workflow",
    "_expand_implied_user_groups",
    "_expand_inheriting_acl_groups",
]
