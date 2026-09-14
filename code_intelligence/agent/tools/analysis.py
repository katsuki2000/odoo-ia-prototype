"""
code_intelligence/ci_agent_node/tools/analysis.py

LangChain @tool wrappers for deeper code analyses (server actions,
security locks, method override cascades, data constraints). Split out
of the former ci_agent_node/agent_tools.py (330 lines) into domain-grouped
submodules -- see tools/__init__.py for the aggregated ALL_CI_TOOLS list.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from code_intelligence.agent.tool_helpers import (
    _require_graph,
    _resolve_model_param,
    WILDCARD_MODEL_ERROR_MSG,
    _is_wildcard_model,
    get_llm_ref,
    find_model_source_filepaths,
    find_server_action_nodes,
    _is_custom_server_action_module,
    _sort_server_action_entries_custom_first,
    _sort_filepaths_custom_first,
    _trace_invoked_methods,
)
from core.evidence.evidence_collector import record_evidence


@tool
def analyze_server_actions(model_name: str) -> str:
    """Analyze server actions (ir.actions.server) and automated rules (base.automation) for a given model."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.rules.server_actions import analyze_server_action_code, interpret_server_action_with_llm

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
    from code_intelligence.rules.security import analyze_python_security_locks

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
    from code_intelligence.rules.override_composer import analyze_method_override_chain_with_evidence as _impl
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
    from code_intelligence.rules.data_constraints import analyze_data_constraints_from_filepaths

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


__all__ = [
    "analyze_server_actions",
    "analyze_security_locks",
    "analyze_method_override_chain",
    "analyze_data_constraints",
]
