"""
code_intelligence/ci_agent_node/tools/introspection.py

LangChain @tool wrappers for module/graph introspection and raw source
reading (role resolution, involved modules, decision-path explanation,
precise source slices).
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from code_intelligence.agent.ci_agent_node.context.tool_helpers import (
    _require_graph,
    _resolve_model_param,
)
from core.evidence.evidence_collector import record_evidence


@tool
def resolve_technical_name(technical_name: str) -> str:
    """Resolve technical group XML-ID (e.g. sales_team.group_sale_manager) to business role name."""
    from code_intelligence.agent.ci_agent_node.context.auxiliary_tools import resolve_technical_name_to_role as _impl
    return _impl(technical_name)


@tool
def list_involved_modules(model_name: str) -> str:
    """List Odoo modules defining or extending a model, each tagged with its role."""
    from code_intelligence.agent.ci_agent_node.context.auxiliary_tools import list_involved_modules_with_evidence as _impl
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
    from code_intelligence.agent.ci_agent_node.context.auxiliary_tools import explain_decision_path as _impl
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
    from code_intelligence.agent.ci_agent_node.context.auxiliary_tools import read_precise_source_code as _impl
    return _impl(filepath, line_start, line_end)


__all__ = [
    "resolve_technical_name",
    "list_involved_modules",
    "explain_decision_path",
    "read_source_code",
]
