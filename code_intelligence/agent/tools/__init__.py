"""Code Intelligence tools and the bounded tool set exposed to the PoC agent."""

from .access import (
    who_has_access_to,
    evaluate_rules_raw,
    evaluate_record_rules,
)
from .structure import (
    field_change_impact,
    button_execution_path,
    trace_full_inheritance,
    describe_workflow,
    describe_navigation_path,
)
from .introspection import (
    resolve_technical_name,
    list_involved_modules,
    explain_decision_path,
    read_source_code,
    inspect_module_extensions,
)
from .analysis import (
    analyze_server_actions,
    analyze_security_locks,
    analyze_method_override_chain,
    analyze_data_constraints,
)
from .source import read_source_fragment, search_system

ALL_CI_TOOLS = [
    who_has_access_to,
    evaluate_record_rules,
    analyze_server_actions,
    analyze_security_locks,
    analyze_method_override_chain,
    analyze_data_constraints,
    button_execution_path,
    describe_workflow,
    describe_navigation_path,
]

__all__ = [
    "who_has_access_to",
    "evaluate_rules_raw",
    "evaluate_record_rules",
    "field_change_impact",
    "button_execution_path",
    "trace_full_inheritance",
    "describe_workflow",
    "describe_navigation_path",
    "resolve_technical_name",
    "list_involved_modules",
    "explain_decision_path",
    "read_source_code",
    "inspect_module_extensions",
    "analyze_server_actions",
    "analyze_security_locks",
    "analyze_method_override_chain",
    "analyze_data_constraints",
    "ALL_CI_TOOLS",
    "search_system",
    "read_source_fragment",
]
