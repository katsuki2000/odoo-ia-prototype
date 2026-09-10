"""
code_intelligence/ci_agent_node/tools/__init__.py

- access.py: ACL + ir.rule permission evaluation.
- structure.py: field impact, button path, inheritance, workflow, navigation.
- introspection.py: role resolution, involved modules, decision-path, raw source.
- analysis.py: server actions, security locks, override cascades, data constraints.

Re-exports every tool function plus ALL_CI_TOOLS so existing callers can do
`from code_intelligence.agent.ci_agent_node.tools import ALL_CI_TOOLS, who_has_access_to`
unchanged in shape from the former `...agent_tools import ...`. Helper
symbols (set_graph_ref, find_model_source_filepaths, etc.) are NOT
re-exported here -- they are canonically defined in tool_helpers.py and
callers should import them from there directly (see Section 613/615 fix
for the same class of unnecessary indirection on CI_SYSTEM_PROMPT).
"""

from code_intelligence.agent.ci_agent_node.tools.access import (
    who_has_access_to,
    evaluate_rules_raw,
    evaluate_record_rules,
)
from code_intelligence.agent.ci_agent_node.tools.structure import (
    field_change_impact,
    button_execution_path,
    trace_full_inheritance,
    describe_workflow,
    describe_navigation_path,
)
from code_intelligence.agent.ci_agent_node.tools.introspection import (
    resolve_technical_name,
    list_involved_modules,
    explain_decision_path,
    read_source_code,
)
from code_intelligence.agent.ci_agent_node.tools.analysis import (
    analyze_server_actions,
    analyze_security_locks,
    analyze_method_override_chain,
    analyze_data_constraints,
)

ALL_CI_TOOLS = [
    list_involved_modules,
    who_has_access_to,
    evaluate_record_rules,
    analyze_server_actions,
    analyze_security_locks,
    analyze_method_override_chain,
    analyze_data_constraints,
    field_change_impact,
    button_execution_path,
    trace_full_inheritance,
    describe_workflow,
    describe_navigation_path,
    resolve_technical_name,
    explain_decision_path,
    read_source_code,
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
    "analyze_server_actions",
    "analyze_security_locks",
    "analyze_method_override_chain",
    "analyze_data_constraints",
    "ALL_CI_TOOLS",
]
