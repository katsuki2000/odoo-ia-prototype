"""
code_intelligence/ci_agent_node/tools/structure.py

LangChain @tool wrappers for structural/graph analyses (field impact,
button execution path, inheritance, workflow, navigation). Split out of
the former ci_agent_node/agent_tools.py (330 lines) into domain-grouped
submodules -- see tools/__init__.py for the aggregated ALL_CI_TOOLS list.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from code_intelligence.agent.tool_helpers import (
    _require_graph,
    _resolve_model_param,
)
from core.evidence.evidence_collector import record_evidence


@tool
def field_change_impact(field_name: str, model_name: str) -> str:
    """Analyze upstream triggers and downstream computed fields when modifying a model field."""
    from code_intelligence.rules.structure import field_change_impact as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, field_name, model_name)
    record_evidence(result.evidence)
    parts = [result.summary_text]
    if result.upstream_triggers:
        parts.append(f"Upstream triggers: {', '.join(result.upstream_triggers)}")
    if result.downstream_computed_fields:
        parts.append(f"Downstream impacted fields: {', '.join(result.downstream_computed_fields)}")
    return "\n".join(parts)


@tool
def button_execution_path(button_name: str, model_name: str, user_groups_json: str = "[]") -> str:
    """Trace UI button execution path, method called, workflow transition, and required groups."""
    from code_intelligence.rules.button_path import button_execution_path as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    try:
        user_groups = json.loads(user_groups_json) if isinstance(user_groups_json, str) else user_groups_json
    except Exception:
        user_groups = None
    result = _impl(G, button_name, model_name, user_groups=user_groups)
    record_evidence(result.evidence)
    return result.summary_text + "\n" + "\n".join(result.execution_steps)


@tool
def trace_full_inheritance(model_name: str) -> str:
    """Trace full _inherit extension and _inherits delegation hierarchy for an Odoo model."""
    from code_intelligence.rules.structure import trace_full_inheritance as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    record_evidence(result.evidence)
    return result.summary_text


@tool
def describe_workflow(model_name: str) -> str:
    """Inspect workflow states, state field, and state machine transitions for an Odoo model."""
    from code_intelligence.rules.workflow import describe_workflow as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    record_evidence(result.evidence)
    return result.summary_text


@tool
def describe_navigation_path(model_name: str, button_label_or_name: str = "", user_groups_json: str = "[]") -> str:
    """Describe the UI navigation path (menu -> action -> button) to reach a model,"""
    from code_intelligence.rules.navigation import describe_navigation_path as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    try:
        user_groups = json.loads(user_groups_json) if isinstance(user_groups_json, str) else user_groups_json
    except Exception:
        user_groups = None
    result = _impl(G, model_name, button_label_or_name, user_groups=user_groups)
    record_evidence(result.evidence)
    return result.summary_text + "\n" + "\n".join(result.execution_steps)


__all__ = [
    "field_change_impact",
    "button_execution_path",
    "trace_full_inheritance",
    "describe_workflow",
    "describe_navigation_path",
]
