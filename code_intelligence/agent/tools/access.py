"""
code_intelligence/ci_agent_node/tools/access.py

LangChain @tool wrappers for access/permission evaluation (ACL + ir.rule).
Split out of the former ci_agent_node/agent_tools.py (330 lines) into
domain-grouped submodules -- see tools/__init__.py for the aggregated
ALL_CI_TOOLS list.
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from code_intelligence.agent.tool_helpers import (
    _require_graph,
    WILDCARD_MODEL_ERROR_MSG,
    _is_wildcard_model,
    _resolve_model_param,
)
from core.evidence.evidence_collector import record_evidence


@tool
def who_has_access_to(model_name: str, permission: str = "read", group_id: Optional[str] = None) -> str:
    """Evaluate model access rights and list active ir.rule record rules."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.rules.access_evaluator import who_has_access_to as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name, permission=permission, group_id=group_id)
    record_evidence(result.evidence)
    return result.summary_text


def evaluate_rules_raw(model_name: str, permission: str = "read", user_groups_json: str = "[]"):
    """Execute evaluate_record_rules and return RuleEvaluationResult."""
    from code_intelligence.rules.record_rules import evaluate_record_rules as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    try:
        user_groups = json.loads(user_groups_json) if isinstance(user_groups_json, str) else user_groups_json
    except Exception:
        user_groups = []
    return _impl(G, model_name, permission=permission, user_groups=user_groups)


@tool
def evaluate_record_rules(model_name: str, permission: str = "read", user_groups_json: str = "[]") -> str:
    """Evaluate Odoo ir.rule record rules for a model and permission."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    result = evaluate_rules_raw(model_name, permission, user_groups_json)
    record_evidence(result.evidence)
    return result.summary_text


__all__ = ["who_has_access_to", "evaluate_rules_raw", "evaluate_record_rules"]
