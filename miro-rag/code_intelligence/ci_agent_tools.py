"""
code_intelligence/ci_agent_tools.py

LangChain @tool wrappers for all 9 Code Intelligence tools (5 composite + 4 auxiliary).
Bound to LLM inside code_intelligence_agent via bind_tools().
All code and docstrings in English per project coding rules.
"""

import json
import logging
from typing import Optional

from langchain_core.tools import tool

_logger = logging.getLogger(__name__)

_GRAPH_REF = None


def set_graph_ref(G):
    """Set global knowledge graph reference for tool wrappers."""
    global _GRAPH_REF
    _GRAPH_REF = G


def _require_graph():
    """Guard: ensure knowledge graph is initialized before tool execution."""
    if _GRAPH_REF is None:
        raise RuntimeError("Knowledge graph not initialized. Call set_graph_ref(G) first.")
    return _GRAPH_REF


# =====================================================================
# COMPOSITE TOOLS (B.1.1 - B.1.5)
# =====================================================================

@tool
def qui_a_acces_a(model_name: str, droit: str = "read", group_id: Optional[str] = None) -> str:
    """Evaluate model access rights and list active ir.rule record rules. Call ONCE per model without group_id unless testing a single group."""
    from code_intelligence.deterministic_tools import qui_a_acces_a as _impl
    G = _require_graph()
    result = _impl(G, model_name, droit=droit, group_id=group_id)
    return result.summary_text


@tool
def impact_changement_champ(field_name: str, model_name: str) -> str:
    """Analyze upstream triggers and downstream computed fields when modifying a model field."""
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
    """Trace UI button execution path, method called, workflow transition, and required groups."""
    from code_intelligence.deterministic_tools import chemin_execution_bouton as _impl
    G = _require_graph()
    result = _impl(G, button_name, model_name)
    return result.summary_text + "\n" + "\n".join(result.execution_steps)


@tool
def suivre_heritage_complet(model_name: str) -> str:
    """Trace full _inherit extension and _inherits delegation hierarchy for an Odoo model."""
    from code_intelligence.deterministic_tools import suivre_heritage_complet as _impl
    G = _require_graph()
    result = _impl(G, model_name)
    return result.summary_text


@tool
def quel_est_le_processus_de(model_name: str) -> str:
    """Get ordered workflow state machine transitions for an Odoo model."""
    from code_intelligence.deterministic_tools import quel_est_le_processus_de as _impl
    G = _require_graph()
    result = _impl(G, model_name)
    return result.summary_text


# =====================================================================
# AUXILIARY TOOLS (B.2.1 - B.2.4)
# =====================================================================

@tool
def resoudre_nom_technique(nom_technique: str) -> str:
    """Resolve technical group XML-ID (e.g. sales_team.group_sale_manager) to business role name."""
    from code_intelligence.auxiliary_tools import resoudre_nom_technique_vers_role as _impl
    return _impl(nom_technique)


@tool
def lister_modules_impliques(model_name: str) -> str:
    """List Odoo modules defining or extending a model."""
    from code_intelligence.auxiliary_tools import lister_modules_impliques as _impl
    G = _require_graph()
    modules = _impl(G, model_name)
    if modules:
        return f"Modules implicated for model '{model_name}': {', '.join(modules)}"
    return f"No modules found for model '{model_name}' in the indexed knowledge graph."


@tool
def expliquer_chemin(path_nodes_json: str) -> str:
    """Explain graph path (JSON list of node IDs) in natural language."""
    from code_intelligence.auxiliary_tools import expliquer_chemin_de_decision as _impl
    G = _require_graph()
    try:
        path_nodes = json.loads(path_nodes_json)
    except (json.JSONDecodeError, TypeError):
        return "Error: path_nodes_json must be a valid JSON list of node IDs."
    return _impl(G, path_nodes)


@tool
def lire_code_source(filepath: str, line_start: int, line_end: int) -> str:
    """Read precise slice of source code lines (max 200 lines)."""
    from code_intelligence.auxiliary_tools import lire_code_source_precis as _impl
    return _impl(filepath, line_start, line_end)


# =====================================================================
# TOOL REGISTRY
# =====================================================================

ALL_CI_TOOLS = [
    lister_modules_impliques,
    qui_a_acces_a,
    impact_changement_champ,
    chemin_execution_bouton,
    suivre_heritage_complet,
    quel_est_le_processus_de,
    resoudre_nom_technique,
    expliquer_chemin,
    lire_code_source,
]
