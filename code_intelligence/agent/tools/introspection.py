"""Graph introspection and confined, line-scoped source reading."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import logging

import networkx as nx

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from code_intelligence.rules.model_suggestions import model_not_found_message, module_not_found_message
from code_intelligence.agent.tools.source_reader import _allowed_source_roots, read_precise_source_code

_logger = logging.getLogger(__name__)

TECHNICAL_TO_BUSINESS_ROLES: Dict[str, str] = {
    "base.group_user": "Utilisateur Interne",
    "base.group_system": "Administrateur Système",
    "base.group_erp_manager": "Gestionnaire des Paramètres",
    "sales_team.group_sale_salesman": "Vendeur (Propres documents uniquement)",
    "sales_team.group_sale_salesman_all_leads": "Vendeur (Tous les documents)",
    "sales_team.group_sale_manager": "Responsable Ventes",
    "account.group_account_user": "Comptable",
    "account.group_account_manager": "Responsable Comptabilité",
    "account.group_account_invoice": "Facturation",
    "stock.group_stock_user": "Agent de Stock",
    "stock.group_stock_manager": "Responsable Inventaire",
    "hr.group_hr_user": "Agent RH",
    "hr.group_hr_manager": "Responsable RH",
}


def resolve_technical_name_to_role(technical_name: str, G: Optional[nx.DiGraph] = None) -> str:
    """Resolve a group to an evidenced display name without inventing translations."""
    clean_id = technical_name.strip()
    if clean_id in TECHNICAL_TO_BUSINESS_ROLES:
        return TECHNICAL_TO_BUSINESS_ROLES[clean_id]
    if G is not None:
        from code_intelligence.rules.group_resolver import get_group_display_name
        display_name = get_group_display_name(G, clean_id)
        if display_name:
            return display_name
    return f"Unknown role ({clean_id})"


def list_involved_modules_flat(G: nx.DiGraph, model_name: str) -> List[str]:
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []
    modules: Set[str] = set()
    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "DEFINED_IN" and neighbor.startswith("module:"):
            modules.add(neighbor.replace("module:", ""))
    return sorted(list(modules)) if modules else ["base"]


def _read_defined_in_edges(G: nx.DiGraph, model_name: str) -> List[Tuple[str, str]]:
    """Read actual DEFINED_IN edges, without the display fallback."""
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []
    entries: List[Tuple[str, str]] = []
    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "DEFINED_IN" and neighbor.startswith("module:"):
            entries.append((neighbor.replace("module:", ""), edge_data.get("role", "unknown")))
    return entries


def list_involved_modules_with_role(G: nx.DiGraph, model_name: str) -> List[Tuple[str, str]]:
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []
    entries = _read_defined_in_edges(G, model_name)
    return sorted(entries) if entries else [("base", "unknown")]


@dataclass
class InvolvedModulesResult:
    modules: List[Tuple[str, str]]
    evidence: List[Evidence] = field(default_factory=list)


def _build_involved_modules_evidence(model_name: str, entries: List[Tuple[str, str]]) -> List[Evidence]:
    if not entries:
        return [make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(f"No DEFINED_IN edge found for model '{model_name}' in the "
                   "indexed knowledge graph (model not found, or found with "
                   "no declares/extends edge)"),
            source=f"involved_modules:{model_name}:no_edges", value=0, confidence="HIGH", scope={},
        )]
    return [make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=f"Module '{module}' {role} model '{model_name}'",
        source=f"involved_modules:{model_name}:{module}", value=role, confidence="HIGH", scope={},
    ) for module, role in entries]


def list_involved_modules_with_evidence(G: nx.DiGraph, model_name: str) -> InvolvedModulesResult:
    entries = _read_defined_in_edges(G, model_name)
    if f"model:{model_name}" not in G:
        modules: List[Tuple[str, str]] = []
    else:
        modules = sorted(entries) if entries else [("base", "unknown")]
    return InvolvedModulesResult(modules=modules, evidence=_build_involved_modules_evidence(model_name, entries))


def _explain_decision_path_impl(G: nx.DiGraph, path_nodes: List[str]) -> str:
    if not path_nodes:
        return "No path specified."
    for node_id in path_nodes:
        if node_id not in G:
            return f"Error: path contains unknown graph node '{node_id}'."
    steps = []
    for idx in range(len(path_nodes) - 1):
        u = str(path_nodes[idx])
        v = str(path_nodes[idx + 1])
        edge_data = G.get_edge_data(u, v)
        if edge_data is None:
            return f"Error: no graph edge exists from '{u}' to '{v}'."
        u_data = G.nodes[u]
        v_data = G.nodes[v]
        edge_type = edge_data.get("edge_type")
        if not edge_type:
            return f"Error: graph edge from '{u}' to '{v}' has no declared edge type."
        u_type = u_data.get("node_type", u.split(":")[0])
        v_type = v_data.get("node_type", v.split(":")[0])
        if edge_type == "RESTRICTED_BY":
            steps.append(f"Step {idx + 1}: Model '{u}' is restricted by Security Rule '{v}' (Domain: `{v_data.get('domain_force', '')}`).")
        elif edge_type == "APPLIES_TO_GROUP":
            steps.append(f"Step {idx + 1}: Security Rule '{u}' applies to Group '{v}'.")
        elif edge_type == "IMPLIES":
            child_role = resolve_technical_name_to_role(u.replace("group:", ""), G)
            parent_role = resolve_technical_name_to_role(v.replace("group:", ""), G)
            steps.append(f"Step {idx + 1}: Group '{u}' ({child_role}) inherits permissions from '{v}' ({parent_role}).")
        elif edge_type == "EXTENDS":
            steps.append(f"Step {idx + 1}: Model '{u}' extends model '{v}' via `_inherit`.")
        elif edge_type == "TRANSITIONS_VIA":
            records = edge_data.get("button_transitions") or [edge_data]
            methods = sorted({record.get("method_name", "") for record in records if record.get("method_name")})
            method_text = ", ".join(f"`{method}()`" for method in methods) or "an indexed button method"
            steps.append(f"Step {idx + 1}: State '{u}' transitions to '{v}' via {method_text}.")
        else:
            steps.append(f"Step {idx + 1}: {u_type} '{u}' --[{edge_type}]--> {v_type} '{v}'.")
    return "\n".join(steps)




import json
from langchain_core.tools import tool
from code_intelligence.agent.tools.helpers import _require_graph, _resolve_model_param
from core.evidence.evidence_collector import record_evidence


@tool
def resolve_technical_name(technical_name: str) -> str:
    """Resolve technical group XML-ID (e.g. sales_team.group_sale_manager) to business role name."""
    return resolve_technical_name_to_role(technical_name, _require_graph())


def _describe_module_models(G: nx.DiGraph, module_name: str) -> str:
    module_node = f"module:{module_name}"
    models_with_role = sorted(
        f"{pred[len('model:'):]} ({(G.get_edge_data(pred, module_node) or {}).get('role', 'extends')})"
        for pred in G.predecessors(module_node)
        if pred.startswith("model:")
    )
    if not models_with_role:
        return f"Module '{module_name}' defines or extends no model in the indexed knowledge graph."
    return f"Module '{module_name}' defines or extends the following models: {', '.join(models_with_role)}."


@tool
def list_involved_modules(model_name: str) -> str:
    """List Odoo modules defining or extending a model, each tagged with its role."""
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    if not G.has_node(f"model:{model_name}"):
        if G.has_node(f"module:{model_name}"):
            return _describe_module_models(G, model_name)
        return model_not_found_message(G, model_name)
    result = list_involved_modules_with_evidence(G, model_name)
    record_evidence(result.evidence)
    formatted = ", ".join(f"{mod} ({role})" for mod, role in result.modules)
    ambiguity_note = (
        " [SYMBOLE AMBIGU: plusieurs modules candidats -- ne pas en choisir un "
        "arbitrairement, les présenter tous ou demander à l'utilisateur de trancher]"
        if len(result.modules) > 1 else ""
    )
    return f"Modules implicated for model '{model_name}': {formatted}.{ambiguity_note}"


@tool
def explain_decision_path(path_nodes_json: str) -> str:
    """Explain graph path (JSON list of node IDs) in natural language."""
    G = _require_graph()
    try:
        path_nodes = json.loads(path_nodes_json)
    except (json.JSONDecodeError, TypeError):
        return "Error: path_nodes_json must be a valid JSON list of node IDs."
    if not isinstance(path_nodes, list) or not all(isinstance(n, str) for n in path_nodes):
        return ('Error: path_nodes_json must be a JSON list of string node IDs '
                '(e.g. ["model:account.move", "rule:xyz"]), not numbers or other types.')
    return _explain_decision_path_impl(G, path_nodes)


@tool
def read_source_code(filepath: str, line_start: int, line_end: int) -> str:
    """Read precise slice of source code lines (max 200 lines)."""
    return read_precise_source_code(filepath, line_start, line_end, include_citation=True)


@tool
def inspect_module_extensions(module_name: str) -> str:
    """Inspect native models extended by an Odoo module outside its own perimeter,
    including Python class names, source files, and added fields/methods."""
    from code_intelligence.rules.structure import inspect_module_cross_domain_extensions, format_module_cross_domain_extensions
    G = _require_graph()
    if not G.has_node(f"module:{module_name}"):
        return module_not_found_message(G, module_name)
    extensions = inspect_module_cross_domain_extensions(G, module_name)
    return format_module_cross_domain_extensions(extensions, module_name)


__all__ = [
    "resolve_technical_name", "list_involved_modules", "explain_decision_path",
    "read_source_code", "inspect_module_extensions",
]
