"""
code_intelligence/ci_agent_node/tools/introspection_impl.py

Introspection tool implementations Deferred-imported by introspection.py's
@tool wrappers, same pattern as the other tools/*.py submodules.
  - resolve_technical_name_to_role(technical_name)
  - list_involved_modules_flat(G, model_name)
  - list_involved_modules_with_role(G, model_name)
  - explain_decision_path(path_nodes)
  - read_precise_source_code(filepath, line_start, line_end)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
import logging

import networkx as nx

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence

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
    """Resolves technical group XML-ID to human-readable business role."""
    clean_id = technical_name.strip()
    if clean_id in TECHNICAL_TO_BUSINESS_ROLES:
        return TECHNICAL_TO_BUSINESS_ROLES[clean_id]

    short_id = clean_id.split(".")[-1] if "." in clean_id else clean_id
    formatted = short_id.replace("group_", "").replace("_", " ").title()
    return formatted


def list_involved_modules_flat(G: nx.DiGraph, model_name: str) -> List[str]:
    """Lists all modules that define or extend a given model.

    Renamed from `list_involved_modules` (Section 733): the Option C merge of
    introspection_impl.py into introspection.py collapsed two distinct
    symbols (this raw flat-list function, and the @tool-decorated wrapper
    below, ex-separate modules) onto the same name -- the later definition
    silently shadowed this one at module level, so
    `tools.introspection.list_involved_modules` always resolved to the
    StructuredTool, breaking every direct caller of the flat function
    (TypeError: 'StructuredTool' object is not callable). The @tool wrapper
    keeps the `list_involved_modules` name since it is looked up by that
    exact string in ctx.tool_map (predispatch_structure.py) and registered
    in ALL_CI_TOOLS.
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


def _read_defined_in_edges(G: nx.DiGraph, model_name: str) -> List[Tuple[str, str]]:
    """
    Read the REAL DEFINED_IN edges of a model node -- module + role
    ('declares' or 'extends'), in graph iteration order, no sorting, no
    fallback. Single source of truth for both
    list_involved_modules_with_role() (display, with its ['base',
    'unknown'] fallback applied on top) and
    list_involved_modules_with_evidence() (Evidence must never assert that
    fallback as a fact -- see its own docstring).
    """
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
    """
    Returns every candidate module defining or extending the model together
    with its role ('declares' or 'extends').
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []

    entries = _read_defined_in_edges(G, model_name)
    return sorted(entries) if entries else [("base", "unknown")]


@dataclass
class InvolvedModulesResult:
    """
    Composed involved-modules analysis: modules is tuple-for-tuple what
    list_involved_modules_with_role() has always returned (contract
    unchanged for the existing wrapper/tool/tests), plus structured
    Evidence covering the REAL DEFINED_IN edges read from the graph.

    The ['base', 'unknown'] fallback used for display when no real edge is
    found is a UI convenience, not a fact -- it is never asserted as
    Evidence. When no real edge exists, evidence instead carries a single
    explicit negative fact (see _build_involved_modules_evidence).
    """
    modules: List[Tuple[str, str]]
    evidence: List[Evidence] = field(default_factory=list)


def _build_involved_modules_evidence(
    model_name: str, entries: List[Tuple[str, str]]
) -> List[Evidence]:
    if not entries:
        return [make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"No DEFINED_IN edge found for model '{model_name}' in the "
                f"indexed knowledge graph (model not found, or found with "
                f"no declares/extends edge)"
            ),
            source=f"involved_modules:{model_name}:no_edges",
            value=0,
            confidence="HIGH",
            scope={},
        )]

    evidence: List[Evidence] = []
    for module, role in entries:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Module '{module}' {role} model '{model_name}'",
            source=f"involved_modules:{model_name}:{module}",
            value=role,
            confidence="HIGH",
            scope={},
        ))
    return evidence


def list_involved_modules_with_evidence(G: nx.DiGraph, model_name: str) -> InvolvedModulesResult:
    """
    Same public list as list_involved_modules_with_role(), plus structured
    Evidence for the real DEFINED_IN edges backing it (fallback excluded,
    see InvolvedModulesResult docstring).
    """
    entries = _read_defined_in_edges(G, model_name)
    if f"model:{model_name}" not in G:
        modules: List[Tuple[str, str]] = []
    else:
        modules = sorted(entries) if entries else [("base", "unknown")]
    return InvolvedModulesResult(
        modules=modules,
        evidence=_build_involved_modules_evidence(model_name, entries),
    )


def _explain_decision_path_impl(G: nx.DiGraph, path_nodes: List[str]) -> str:
    """Translates a sequence of nodes/edges into step-by-step natural language."""
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
    """Targeted source code reader with max line limit safeguard and sensitive pattern flagging."""
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    from code_intelligence.rules.server_actions import (
        _SUDO_PATTERN,
        _HARDCODED_ID_LIST_PATTERN,
    )
    from code_intelligence.rules.security import _EMAIL_PATTERN

    path = Path(filepath_str)
    target_model_resolved = None

    if not path.exists():
        import re
        from config.settings import (
            _ROOT, CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, OCA_SAMPLE_ADDONS_PATH,
        )
        repo_root = _ROOT
        candidates = [
            repo_root / filepath_str,
            Path(OCA_SAMPLE_ADDONS_PATH) / filepath_str if OCA_SAMPLE_ADDONS_PATH else None,
            Path(CUSTOM_ADDONS_PATH) / filepath_str if CUSTOM_ADDONS_PATH else None,
            Path(CORE_ADDONS_PATH) / filepath_str if CORE_ADDONS_PATH else None,
        ]
        matched = next((c for c in candidates if c and c.exists()), None)
        if matched:
            path = matched
        else:
            norm = filepath_str.lstrip("/").replace("\\", "/")
            found = list(repo_root.glob(f"**/{norm}"))
            if not found:
                parts = norm.split("/")
                if len(parts) >= 2:
                    found = list(repo_root.glob(f"**/{'/'.join(parts[-2:])}"))
            if found:
                path = found[0]
            else:
                from code_intelligence.agent.tool_helpers import _GRAPH_REF
                if _GRAPH_REF is not None:
                    if _GRAPH_REF.has_node(f"model:{filepath_str}"):
                        target_model_resolved = filepath_str
                    else:
                        stem = Path(filepath_str).stem.replace("_", ".")
                        if _GRAPH_REF.has_node(f"model:{stem}"):
                            target_model_resolved = stem
                        else:
                            for _, d in _GRAPH_REF.nodes(data=True):
                                if d.get("node_type") == "Model":
                                    m_name = d.get("name", "")
                                    if m_name and m_name.replace(".", "_") == Path(filepath_str).stem:
                                        target_model_resolved = m_name
                                        break
                    if target_model_resolved:
                        m_fps = _GRAPH_REF.nodes[f"model:{target_model_resolved}"].get("filepaths", [])
                        for fp in m_fps:
                            if Path(fp).exists():
                                path = Path(fp)
                                break
                if not path.exists():
                    return f"Error: File '{filepath_str}' does not exist."

    if target_model_resolved and path.exists() and line_start <= 1:
        try:
            import re
            text = path.read_text(encoding="utf-8")
            pos = re.search(r"(?:_name|_inherit)\s*=\s*['\"]" + re.escape(target_model_resolved) + r"['\"]", text)
            if pos:
                before = text[:pos.start()]
                class_matches = list(re.finditer(r"class\s+\w+", before))
                if class_matches:
                    class_pos = class_matches[-1].start()
                    class_lineno = text[:class_pos].count("\n") + 1
                    line_start = class_lineno
                    line_end = class_lineno + min(max_lines - 1, 150)
        except Exception:
            pass

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

# ── Introspection Tools ─────────────────────────────────────────────────

"""
code_intelligence/ci_agent_node/tools/introspection.py

LangChain @tool wrappers for module/graph introspection and raw source
reading (role resolution, involved modules, decision-path explanation,
precise source slices).
"""


import json

from langchain_core.tools import tool

from code_intelligence.agent.tool_helpers import (
    _require_graph,
    _resolve_model_param,
)
from core.evidence.evidence_collector import record_evidence


@tool
def resolve_technical_name(technical_name: str) -> str:
    """Resolve technical group XML-ID (e.g. sales_team.group_sale_manager) to business role name."""
    return resolve_technical_name_to_role(technical_name)


@tool
def list_involved_modules(model_name: str) -> str:
    """List Odoo modules defining or extending a model, each tagged with its role."""
    _impl = list_involved_modules_with_evidence
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
    return _explain_decision_path_impl(G, path_nodes)


@tool
def read_source_code(filepath: str, line_start: int, line_end: int) -> str:
    """Read precise slice of source code lines (max 200 lines)."""
    return read_precise_source_code(filepath, line_start, line_end)


__all__ = [
    "resolve_technical_name",
    "list_involved_modules",
    "explain_decision_path",
    "read_source_code",
]
