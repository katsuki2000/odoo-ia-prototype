"""
code_intelligence/ci_agent_tools.py

LangChain @tool wrappers for all 9 Code Intelligence tools (5 composite + 4 auxiliary).
These are bound to the LLM inside the code_intelligence_agent_loop via bind_tools().

Story C.1.1: All tools are wrapped with clear docstrings that serve as the tool description
for the LLM to decide which tool to invoke.
"""

import json
import logging
from typing import Optional

from langchain_core.tools import tool

_logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Global graph reference, set once at startup by the agent loop.
# ------------------------------------------------------------------
_GRAPH_REF = None


def set_graph_ref(G):
    """Called once by the agent loop to inject the knowledge graph."""
    global _GRAPH_REF
    _GRAPH_REF = G


def _require_graph():
    """Guard: ensure graph has been injected before any tool call."""
    if _GRAPH_REF is None:
        raise RuntimeError("Knowledge graph not initialized. Call set_graph_ref(G) first.")
    return _GRAPH_REF


# =====================================================================
# COMPOSITE TOOLS (B.1.1 - B.1.5)
# =====================================================================

@tool
def qui_a_acces_a(model_name: str, droit: str = "read", group_id: Optional[str] = None) -> str:
    """Evaluate access rights for a model.
    Returns which groups can access a model for a given permission (read/write/create/unlink).
    Combines CSV ACLs, ir.rule record rules, group hierarchy (implied_ids), and JS client checks.
    Use this when the user asks: "who can access X?", "which groups have write on Y?".
    """
    from code_intelligence.deterministic_tools import qui_a_acces_a as _impl
    G = _require_graph()
    result = _impl(G, model_name, droit=droit, group_id=group_id)
    return result.summary_text


@tool
def impact_changement_champ(field_name: str, model_name: str) -> str:
    """Analyze the impact of modifying a field on a model.
    Returns upstream triggers (fields the computation depends on) and downstream
    computed fields that would be recomputed. Use this when the user asks:
    "what happens if I modify field X?", "which computed fields depend on Y?".
    """
    from code_intelligence.deterministic_tools import impact_changement_champ as _impl
    G = _require_graph()
    result = _impl(G, field_name, model_name)
    parts = [result.summary_text]
    if result.upstream_triggers:
        parts.append(f"Upstream triggers: {', '.join(result.upstream_triggers)}")
    if result.downstream_computed_fields:
        parts.append(f"Downstream impacted fields: {', '.join(result.downstream_computed_fields)}")
    return "\n".join(parts)


@tool
def chemin_execution_bouton(button_name: str, model_name: str) -> str:
    """Trace the execution path of a UI button on a model.
    Returns the Python method called, the workflow state transition, and the security
    groups required. Use this when the user asks: "what does the confirm button do?",
    "what happens when I click cancel on sale.order?".
    """
    from code_intelligence.deterministic_tools import chemin_execution_bouton as _impl
    G = _require_graph()
    result = _impl(G, button_name, model_name)
    return result.summary_text + "\n" + "\n".join(result.execution_steps)


@tool
def suivre_heritage_complet(model_name: str) -> str:
    """Trace the complete inheritance chain of an Odoo model.
    Distinguishes _inherit (extension) from _inherits (delegation).
    Use this when the user asks: "what does sale.order inherit from?",
    "show me the inheritance chain of account.move".
    """
    from code_intelligence.deterministic_tools import suivre_heritage_complet as _impl
    G = _require_graph()
    result = _impl(G, model_name)
    return result.summary_text


@tool
def quel_est_le_processus_de(model_name: str) -> str:
    """Describe the workflow process (state machine) of a model.
    Traverses WorkflowState nodes and TRANSITIONS_VIA edges.
    Returns the ordered sequence of state transitions with button labels,
    methods, and required roles. Use this when the user asks:
    "what is the process for sale.order?", "what are the workflow steps of hr.leave?".
    """
    from code_intelligence.deterministic_tools import quel_est_le_processus_de as _impl
    G = _require_graph()
    result = _impl(G, model_name)
    return result.summary_text


# =====================================================================
# AUXILIARY TOOLS (B.2.1 - B.2.4)
# =====================================================================

@tool
def resoudre_nom_technique(nom_technique: str) -> str:
    """Resolve a technical group XML-ID to its business role name.
    Example: 'sales_team.group_sale_manager' -> 'Responsable Ventes'.
    Use this to make technical group names understandable for the user.
    """
    from code_intelligence.auxiliary_tools import resoudre_nom_technique_vers_role as _impl
    return _impl(nom_technique)


@tool
def lister_modules_impliques(model_name: str) -> str:
    """List all Odoo modules that define or extend a given model.
    IMPORTANT: Always call this tool FIRST before any other tool to scope
    the analysis to the correct modules.
    """
    from code_intelligence.auxiliary_tools import lister_modules_impliques as _impl
    G = _require_graph()
    modules = _impl(G, model_name)
    if modules:
        return f"Modules implicated for model '{model_name}': {', '.join(modules)}"
    return f"No modules found for model '{model_name}' in the indexed knowledge graph."


@tool
def expliquer_chemin(path_nodes_json: str) -> str:
    """Explain a graph traversal path in natural language.
    Input: JSON list of node IDs, e.g. '["model:sale.order", "rule:sale_rule1", "group:sales_team.group_sale_manager"]'.
    Returns a step-by-step explanation of the path through the knowledge graph.
    """
    from code_intelligence.auxiliary_tools import expliquer_chemin_de_decision as _impl
    G = _require_graph()
    try:
        path_nodes = json.loads(path_nodes_json)
    except (json.JSONDecodeError, TypeError):
        return "Error: path_nodes_json must be a valid JSON list of node IDs."
    return _impl(G, path_nodes)


@tool
def lire_code_source(filepath: str, line_start: int, line_end: int) -> str:
    """Read a precise section of source code from a file.
    Limited to 200 lines maximum for safety. Use this when you need to show
    the user the actual Odoo source code for a specific method or class.
    """
    from code_intelligence.auxiliary_tools import lire_code_source_precis as _impl
    return _impl(filepath, line_start, line_end)


# =====================================================================
# TOOL REGISTRY
# =====================================================================

ALL_CI_TOOLS = [
    # Scope first (as per C.1.3 prompt strategy)
    lister_modules_impliques,
    # Composite (B.1)
    qui_a_acces_a,
    impact_changement_champ,
    chemin_execution_bouton,
    suivre_heritage_complet,
    quel_est_le_processus_de,
    # Auxiliary (B.2)
    resoudre_nom_technique,
    expliquer_chemin,
    lire_code_source,
]
