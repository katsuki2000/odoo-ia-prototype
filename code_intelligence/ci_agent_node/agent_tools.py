"""
LangChain @tool wrappers for Code Intelligence tools.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from .tool_helpers import (
    set_graph_ref,
    set_llm_ref,
    get_graph_ref,
    get_llm_ref,
    _require_graph,
    WILDCARD_MODEL_ERROR_MSG,
    _is_wildcard_model,
    _resolve_model_param,
    resolve_model_param,
    find_model_source_filepaths,
    find_security_lock_source_files,
    find_server_action_nodes,
    find_methods_with_override_cascade,
    _is_custom_module_filepath,
    _is_custom_server_action_module,
    _sort_server_action_entries_custom_first,
    _sort_filepaths_custom_first,
    _trace_invoked_methods,
)
from code_intelligence.utils import format_file_link
from core.evidence_collector import record_evidence

_logger = logging.getLogger(__name__)


@tool
def who_has_access_to(model_name: str, permission: str = "read", group_id: Optional[str] = None) -> str:
    """Evaluate model access rights and list active ir.rule record rules."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.deterministic.access.access_evaluator import who_has_access_to as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name, permission=permission, group_id=group_id)
    record_evidence(result.evidence)
    return result.summary_text


@tool
def field_change_impact(field_name: str, model_name: str) -> str:
    """Analyze upstream triggers and downstream computed fields when modifying a model field."""
    from code_intelligence.deterministic.structure.field_impact import field_change_impact as _impl
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
    from code_intelligence.deterministic.navigation.button_path import button_execution_path as _impl
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
    from code_intelligence.deterministic.structure.inheritance_chain import trace_full_inheritance as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    record_evidence(result.evidence)
    return result.summary_text


@tool
def describe_workflow(model_name: str) -> str:
    """Inspect workflow states, state field, and state machine transitions for an Odoo model."""
    from code_intelligence.deterministic.structure.workflow_process import describe_workflow as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    record_evidence(result.evidence)
    return result.summary_text


@tool
def resolve_technical_name(technical_name: str) -> str:
    """Resolve technical group XML-ID (e.g. sales_team.group_sale_manager) to business role name."""
    from code_intelligence.ci_agent_node.auxiliary_tools import resolve_technical_name_to_role as _impl
    return _impl(technical_name)


@tool
def list_involved_modules(model_name: str) -> str:
    """List Odoo modules defining or extending a model, each tagged with its role."""
    from code_intelligence.ci_agent_node.auxiliary_tools import list_involved_modules_with_evidence as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    mod_node = f"module:{model_name}"
    if not G.has_node(f"model:{model_name}") and G.has_node(mod_node):
        models_with_role = []
        for pred in G.predecessors(mod_node):
            if pred.startswith("model:"):
                m = pred.replace("model:", "")
                edge = G.get_edge_data(pred, mod_node) or {}
                role = edge.get("role", "extends")
                models_with_role.append(f"{m} ({role})")
        if models_with_role:
            return f"Module '{model_name}' defines or extends the following models: {', '.join(sorted(models_with_role))}."
    result = _impl(G, model_name)
    record_evidence(result.evidence)
    entries = result.modules
    if entries:
        formatted = ", ".join(f"{mod} ({role})" for mod, role in entries)
        ambiguity_note = (
            " [SYMBOLE AMBIGU: plusieurs modules candidats -- ne pas en choisir un "
            "arbitrairement, les présenter tous ou demander à l'utilisateur de trancher]"
            if len(entries) > 1 else ""
        )
        return f"Modules implicated for model '{model_name}': {formatted}.{ambiguity_note}"
    return f"No modules found for model '{model_name}' in the indexed knowledge graph."


@tool
def explain_decision_path(path_nodes_json: str) -> str:
    """Explain graph path (JSON list of node IDs) in natural language."""
    from code_intelligence.ci_agent_node.auxiliary_tools import explain_decision_path as _impl
    G = _require_graph()
    try:
        path_nodes = json.loads(path_nodes_json)
    except (json.JSONDecodeError, TypeError):
        return "Error: path_nodes_json must be a valid JSON list of node IDs."
    if not isinstance(path_nodes, list) or not all(isinstance(n, str) for n in path_nodes):
        return (
            "Error: path_nodes_json must be a JSON list of string node IDs "
            "(e.g. [\"model:account.move\", \"rule:xyz\"]), not numbers or other types."
        )
    return _impl(G, path_nodes)


@tool
def read_source_code(filepath: str, line_start: int, line_end: int) -> str:
    """Read precise slice of source code lines (max 200 lines)."""
    from code_intelligence.ci_agent_node.auxiliary_tools import read_precise_source_code as _impl
    return _impl(filepath, line_start, line_end)


def evaluate_rules_raw(model_name: str, permission: str = "read", user_groups_json: str = "[]"):
    """Execute evaluate_record_rules and return RuleEvaluationResult."""
    from code_intelligence.deterministic.access.record_rules import evaluate_record_rules as _impl
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


@tool
def analyze_server_actions(model_name: str) -> str:
    """Analyze server actions (ir.actions.server) and automated rules (base.automation) for a given model."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.server_actions import analyze_server_action_code, interpret_server_action_with_llm

    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    sa_nodes = find_server_action_nodes(G, model_name)
    if not sa_nodes:
        return f"No server actions (ir.actions.server) found for model '{model_name}'."

    entries = []
    all_evidence = []
    llm_ref = get_llm_ref()
    for node_id, attrs in sa_nodes:
        xml_id = attrs.get("xml_id", node_id)
        code = attrs.get("code", "")
        analysis = analyze_server_action_code(
            code=code,
            action_xml_id=xml_id,
            action_type=attrs.get("action_type", "server_action"),
            action_name=attrs.get("name", ""),
            user_id=attrs.get("user_id", ""),
            interval_number=attrs.get("interval_number", 1),
            interval_type=attrs.get("interval_type", ""),
        )
        analysis = interpret_server_action_with_llm(analysis, code, llm_ref)
        all_evidence.extend(analysis.evidence)
        summary = analysis.summary_text + _trace_invoked_methods(G, model_name, code)
        entries.append((xml_id, _is_custom_server_action_module(G, xml_id), summary))

    record_evidence(all_evidence)
    entries = _sort_server_action_entries_custom_first(entries)
    return "\n\n".join(summary for _, _, summary in entries)


@tool
def analyze_security_locks(model_name: str) -> str:
    """Analyze Python code for a given model to detect security locks, exception messages, and bypasses."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.security import analyze_python_security_locks

    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    filepaths = find_model_source_filepaths(G, model_name)
    if not filepaths:
        return f"No Python source files located for model '{model_name}'."

    summaries = []
    all_evidence = []
    for fp in _sort_filepaths_custom_first(filepaths):
        p = Path(fp)
        if p.exists():
            code = p.read_text(encoding="utf-8")
            analysis = analyze_python_security_locks(code, fp)
            all_evidence.extend(analysis.evidence)
            summaries.append(analysis.summary_text)

    record_evidence(all_evidence)
    return "\n\n".join(summaries) if summaries else f"No security analysis results for model '{model_name}'."


@tool
def analyze_method_override_chain(model_name: str, method_name: str) -> str:
    """Resolve the REAL execution order of a method overridden across modules in an _inherit cascade."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.overrides import analyze_method_override_chain_with_evidence as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name, method_name, llm=get_llm_ref())
    record_evidence(result.evidence)
    return result.summary_text


@tool
def analyze_data_constraints(model_name: str) -> str:
    """Detect _sql_constraints declarations and relational field domain= conditions for a given model."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.data_constraints.analyzer import analyze_data_constraints_from_filepaths

    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    filepaths = find_model_source_filepaths(G, model_name)
    if not filepaths:
        return f"No Python source files located for model '{model_name}'."

    result = analyze_data_constraints_from_filepaths(model_name, filepaths)
    record_evidence(result.evidence)
    return result.summary_text


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
    resolve_technical_name,
    explain_decision_path,
    read_source_code,
]
