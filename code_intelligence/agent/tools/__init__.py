"""The small, explicit tool surface exposed to the MIRO PoC agent."""

from .access import who_has_access_to, evaluate_record_rules
from .structure import button_execution_path, describe_workflow, describe_navigation_path
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
    "ALL_CI_TOOLS",
    "search_system",
    "read_source_fragment",
    "who_has_access_to",
    "evaluate_record_rules",
    "analyze_server_actions",
    "analyze_security_locks",
    "analyze_method_override_chain",
    "analyze_data_constraints",
    "button_execution_path",
    "describe_workflow",
    "describe_navigation_path",
]
