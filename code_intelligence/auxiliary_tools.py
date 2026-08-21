"""
code_intelligence/auxiliary_tools.py

Auxiliary Tools for Odoo Code Intelligence.
Implements Story B.2:
  - B.2.1: resolve_technical_name_to_role(technical_name)
  - B.2.2: list_involved_modules(G, model_name)
  - B.2.3: explain_decision_path(path_nodes)
  - B.2.4: read_precise_source_code(filepath, line_start, line_end)
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
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


def resolve_technical_name_to_role(technical_name: str) -> str:
    """
    Story B.2.1: Resolves technical group XML-ID to human-readable business role.
    """
    clean_id = technical_name.strip()
    if clean_id in TECHNICAL_TO_BUSINESS_ROLES:
        return TECHNICAL_TO_BUSINESS_ROLES[clean_id]

    # Fallback formatting: group_sale_manager -> Sale Manager
    short_id = clean_id.split(".")[-1] if "." in clean_id else clean_id
    formatted = short_id.replace("group_", "").replace("_", " ").title()
    return formatted


def list_involved_modules(G: nx.DiGraph, model_name: str) -> List[str]:
    """
    Story B.2.2: Lists all modules that define or extend a given model.

    Note: this returns a flat, unordered-role list for backward
    compatibility with existing callers/tests. Since Bloc 8 (J28-29),
    graph_builder.py creates one DEFINED_IN edge per real declaration site
    (not just decls[0]'s module), so this can legitimately return several
    modules for a model that is declared in one and extended in others.
    Callers that need to distinguish "declares" from "extends" per module
    (e.g. to present ambiguous-symbol candidates to the agent/user) should
    use list_involved_modules_with_role() instead.

    The previous field->module fallback (for when no DEFINED_IN edge was
    found) is removed here: it walked field nodes looking for a `module:`
    neighbor, but no such edge is ever created by graph_builder (fields
    only carry HAS_FIELD/COMPUTED_BY/RELATES_TO edges) -- it never found
    anything and was silently dead code.
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []

    modules: Set[str] = set()

    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "DEFINED_IN" and neighbor.startswith("module:"):
            modules.add(neighbor.replace("module:", ""))

    return sorted(list(modules)) if modules else ["base"]


def list_involved_modules_with_role(G: nx.DiGraph, model_name: str) -> List[Tuple[str, str]]:
    """
    Bloc 8 (J28-29): ambiguous-symbol variant of list_involved_modules().

    A model declared with `_name` in one module and extended via
    `_inherit` in one or more other modules is a genuinely ambiguous
    symbol from the agent's point of view -- there is no single "correct"
    origin module. Rather than silently picking the first declaration
    found (the bug this story fixes -- graph_builder.py previously took
    decls[0]'s module only), this returns EVERY candidate module together
    with its role for this model:
      - "declares": the module whose class sets `_name` for this model.
      - "extends":   a module that only extends it via `_inherit` (no
                     `_name` in that declaration).
    Callers (the `list_involved_modules` @tool wrapper, in particular)
    must present all candidates to the agent/user and let them decide,
    never collapse this list to one entry themselves.
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []

    entries: List[Tuple[str, str]] = []
    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "DEFINED_IN" and neighbor.startswith("module:"):
            entries.append((neighbor.replace("module:", ""), edge_data.get("role", "unknown")))

    return sorted(entries) if entries else [("base", "unknown")]


def explain_decision_path(G: nx.DiGraph, path_nodes: List[str]) -> str:
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
            child_role = resolve_technical_name_to_role(u.replace("group:", ""))
            parent_role = resolve_technical_name_to_role(v.replace("group:", ""))
            steps.append(f"Step {idx + 1}: Group '{u}' ({child_role}) inherits permissions from '{v}' ({parent_role}).")
        elif edge_type == "EXTENDS":
            steps.append(f"Step {idx + 1}: Model '{u}' extends model '{v}' via `_inherit`.")
        elif edge_type == "TRANSITIONS_VIA":
            steps.append(f"Step {idx + 1}: State '{u}' transitions to '{v}' via method `{edge_data.get('method_name')}()`.")
        else:
            steps.append(f"Step {idx + 1}: {u_type} '{u}' --[{edge_type}]--> {v_type} '{v}'.")

    return "\n".join(steps)


def read_precise_source_code(filepath_str: str, line_start: int, line_end: int, max_lines: int = 200) -> str:
    """
    Story B.2.4: Targeted source code reader with max line limit safeguard.

    Bloc 7 follow-up (2026-08-21, todo/contexte.txt section 86) : ce lecteur
    de code source brut ne passait jamais par un analyseur (semgrep_locks_
    analyzer.py / server_action_analyzer.py), donc ne pouvait jamais porter
    SENSITIVE_BYPASS_MARKER -- une ligne contenant un contournement reel
    (sudo(), IDs/emails codes en dur) etait renvoyee telle quelle a l'agent
    ReAct, hors de portee de la redaction d'authorization_gate.py, quels que
    soient les droits reels du demandeur. Chaque ligne selectionnee est
    desormais scannee avec les MEMES patterns deja fiables utilises par les
    analyseurs (reimportes, pas redefinis) ; une ligne qui matche est taguee
    avec le meme marqueur partage -- authorization_gate.py::gate_observation
    (deja appele generiquement sur CHAQUE outil dans la boucle ReAct de
    ci_agent_node.py) la redacte alors exactement comme il le fait deja pour
    les sorties des deux analyseurs, sans aucun changement necessaire dans
    authorization_gate.py lui-meme.

    Cet outil ne recoit jamais de model_name (seulement un chemin de
    fichier) -- gate_observation() est donc toujours appele avec
    model_name="", ce qui fait echouer _has_elevated_access() a False pour
    tout demandeur (fail-closed assume, voir todo/contexte.txt section 86
    pour la justification complete).
    """
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    from code_intelligence.server_action_analyzer import (
        _SUDO_PATTERN,
        _HARDCODED_ID_LIST_PATTERN,
    )
    from code_intelligence.semgrep_locks_analyzer import _EMAIL_PATTERN

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
            tag = ""
            if (
                _SUDO_PATTERN.search(line)
                or _HARDCODED_ID_LIST_PATTERN.search(line)
                or _EMAIL_PATTERN.search(line)
            ):
                tag = f"  {SENSITIVE_BYPASS_MARKER} Contenu source sensible detecte sur cette ligne (lecture brute)"
            snippet.append(f"{i:4d} | {line}{tag}")

        return "\n".join(snippet)

    except Exception as e:
        _logger.error("Error reading file %s: %s", filepath_str, e)
        return f"Error reading file '{filepath_str}': {str(e)}"
