"""
code_intelligence/auxiliary_tools.py

Auxiliary Tools for Odoo Code Intelligence.
Implements Story B.2:
  - B.2.1: resoudre_nom_technique_vers_role(nom_technique)
  - B.2.2: lister_modules_impliques(G, model_name)
  - B.2.3: expliquer_chemin_de_decision(path_nodes)
  - B.2.4: lire_code_source_precis(filepath, line_start, line_end)
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Any
import logging

import networkx as nx

_logger = logging.getLogger(__name__)


TECHNICAL_TO_BUSINESS_ROLES: Dict[str, str] = {
    "base.group_user": "Utilisateur Interne (Employee)",
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


def resoudre_nom_technique_vers_role(nom_technique: str) -> str:
    """
    Story B.2.1: Resolves technical group XML-ID to human-readable business role.
    """
    clean_id = nom_technique.strip()
    if clean_id in TECHNICAL_TO_BUSINESS_ROLES:
        return TECHNICAL_TO_BUSINESS_ROLES[clean_id]

    # Fallback formatting: group_sale_manager -> Sale Manager
    short_id = clean_id.split(".")[-1] if "." in clean_id else clean_id
    formatted = short_id.replace("group_", "").replace("_", " ").title()
    return formatted


def lister_modules_impliques(G: nx.DiGraph, model_name: str) -> List[str]:
    """
    Story B.2.2: Lists all modules that define or extend a given model.
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []

    modules: Set[str] = set()

    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "DEFINED_IN" and neighbor.startswith("module:"):
            modules.add(neighbor.replace("module:", ""))

    # If no DEFINED_IN edge found, check model node attribute or module prefix
    m_data = G.nodes[model_node]
    if "inherits_list" in m_data:
        # Check connected field/method definitions for module source
        for field_node in G.neighbors(model_node):
            if field_node.startswith("field:"):
                for mod_node in G.neighbors(field_node):
                    if mod_node.startswith("module:"):
                        modules.add(mod_node.replace("module:", ""))

    return sorted(list(modules)) if modules else ["base"]


def expliquer_chemin_de_decision(G: nx.DiGraph, path_nodes: List[str]) -> str:
    """
    Story B.2.3: Translates a sequence of nodes/edges into step-by-step natural language.
    """
    if not path_nodes:
        return "No path specified."

    steps = []
    for idx in range(len(path_nodes) - 1):
        u = str(path_nodes[idx])
        v = str(path_nodes[idx + 1])

        u_data = G.nodes.get(u, {})
        v_data = G.nodes.get(v, {})
        edge_data = G.get_edge_data(u, v) or {}
        edge_type = edge_data.get("edge_type", "CONNECTED_TO")

        u_type = u_data.get("node_type", u.split(":")[0])
        v_type = v_data.get("node_type", v.split(":")[0])

        if edge_type == "RESTRICTED_BY":
            steps.append(f"Step {idx + 1}: Model '{u}' is restricted by Security Rule '{v}' (Domain: `{v_data.get('domain_force', '')}`).")
        elif edge_type == "APPLIES_TO_GROUP":
            steps.append(f"Step {idx + 1}: Security Rule '{u}' applies to Group '{v}'.")
        elif edge_type == "IMPLIES":
            child_role = resoudre_nom_technique_vers_role(u.replace("group:", ""))
            parent_role = resoudre_nom_technique_vers_role(v.replace("group:", ""))
            steps.append(f"Step {idx + 1}: Group '{u}' ({child_role}) inherits permissions from '{v}' ({parent_role}).")
        elif edge_type == "EXTENDS":
            steps.append(f"Step {idx + 1}: Model '{u}' extends model '{v}' via `_inherit`.")
        elif edge_type == "TRANSITIONS_VIA":
            steps.append(f"Step {idx + 1}: State '{u}' transitions to '{v}' via method `{edge_data.get('method_name')}()`.")
        else:
            steps.append(f"Step {idx + 1}: {u_type} '{u}' --[{edge_type}]--> {v_type} '{v}'.")

    return "\n".join(steps)


def lire_code_source_precis(filepath_str: str, line_start: int, line_end: int, max_lines: int = 200) -> str:
    """
    Story B.2.4: Targeted source code reader with max line limit safeguard.
    """
    path = Path(filepath_str)

    if not path.exists():
        return f"Error: File '{filepath_str}' does not exist."

    requested_lines = line_end - line_start + 1
    if requested_lines > max_lines:
        return f"Error: Line range ({requested_lines} lines) exceeds maximum safeguard limit of {max_lines} lines."

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        total_lines = len(lines)

        start_idx = max(0, line_start - 1)
        end_idx = min(total_lines, line_end)

        selected_lines = lines[start_idx:end_idx]

        snippet = []
        for i, line in enumerate(selected_lines, start=start_idx + 1):
            snippet.append(f"{i:4d} | {line}")

        return "\n".join(snippet)

    except Exception as e:
        _logger.error("Error reading file %s: %s", filepath_str, e)
        return f"Error reading file '{filepath_str}': {str(e)}"
