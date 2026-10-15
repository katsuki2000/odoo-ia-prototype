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
from typing import Dict, List, Optional, Set, Tuple
import logging

import networkx as nx

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence

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
    """Lists all modules that define or extend a given model.
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


def _allowed_source_roots() -> list:
    """Configured addon roots plus the roots the active graph was built from."""
    import code_intelligence.agent.tool_helpers as th
    from config.settings import (
        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS,
        OCA_SAMPLE_ADDONS_PATH,
    )

    graph_roots = th._GRAPH_REF.graph.get("addon_roots_ordered", ()) if th._GRAPH_REF is not None else ()
    configured = (
        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS,
        OCA_SAMPLE_ADDONS_PATH, *graph_roots,
    )
    return [Path(root).resolve() for root in dict.fromkeys(configured) if root and Path(root).exists()]


def read_precise_source_code(
    filepath_str: str, line_start: int, line_end: int, max_lines: int = 200,
    include_citation: bool = False,
) -> str:
    """Targeted source code reader with max line limit safeguard and sensitive pattern flagging."""
    from code_intelligence.agent.source_boundary import validate_source_range

    rangeError = validate_source_range(line_start, line_end, max_lines)
    if rangeError:
        return rangeError
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    from code_intelligence.rules.server_actions import (
        _SUDO_PATTERN,
        _HARDCODED_ID_LIST_PATTERN,
    )
    from code_intelligence.rules.security import _EMAIL_PATTERN

    path = Path(filepath_str)
    target_model_resolved = None

    if not path.exists() and Path("/" + filepath_str).exists():
        path = Path("/" + filepath_str)

    if not path.exists():
        import re
        from config.settings import (
            _ROOT, CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS, OCA_SAMPLE_ADDONS_PATH,
        )
        candidates = [
            *(
                Path(custom_root) / filepath_str
                for custom_root in dict.fromkeys((CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS)) if custom_root
            ),
            Path(CORE_ADDONS_PATH) / filepath_str if CORE_ADDONS_PATH else None,
            Path(OCA_SAMPLE_ADDONS_PATH) / filepath_str if OCA_SAMPLE_ADDONS_PATH else None,
            _ROOT / filepath_str,
        ]
        matched = next((c for c in candidates if c and c.exists()), None)
        if matched:
            path = matched
        else:
            import code_intelligence.agent.tool_helpers as th
            if th._GRAPH_REF is not None:
                if th._GRAPH_REF.has_node(f"model:{filepath_str}"):
                    target_model_resolved = filepath_str
                else:
                    stem = Path(filepath_str).stem.replace("_", ".")
                    if th._GRAPH_REF.has_node(f"model:{stem}"):
                        target_model_resolved = stem
                    else:
                        for _, d in th._GRAPH_REF.nodes(data=True):
                            if d.get("node_type") == "Model":
                                m_name = d.get("name", "")
                                if m_name and m_name.replace(".", "_") == Path(filepath_str).stem:
                                    target_model_resolved = m_name
                                    break
                if target_model_resolved:
                    m_fps = th._GRAPH_REF.nodes[f"model:{target_model_resolved}"].get("filepaths", [])
                    for fp in m_fps:
                        p_candidate = Path(fp)
                        if p_candidate.exists() and not any(part in ("tests", "test", ".git", ".venv") for part in p_candidate.parts):
                            path = p_candidate
                            break

            if not path.exists():
                corpus_roots = [
                    p for p in [
                        Path(CORE_ADDONS_PATH) if CORE_ADDONS_PATH else None,
                        *(
                            Path(custom_root)
                            for custom_root in dict.fromkeys((CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS))
                            if custom_root
                        ),
                        Path(OCA_SAMPLE_ADDONS_PATH) if OCA_SAMPLE_ADDONS_PATH else None,
                    ]
                    if p and p.exists()
                ]
                norm = filepath_str.lstrip("/").replace("\\", "/")
                parts = norm.split("/")
                tail_pattern = f"**/{norm}"
                short_pattern = f"**/{'/'.join(parts[-2:])}" if len(parts) >= 2 else None

                for root in corpus_roots:
                    matches = [
                        f for f in root.glob(tail_pattern)
                        if not any(part in ("tests", "test", ".git", ".venv", "__pycache__") for part in f.parts)
                    ]
                    if not matches and short_pattern:
                        matches = [
                            f for f in root.glob(short_pattern)
                            if not any(part in ("tests", "test", ".git", ".venv", "__pycache__") for part in f.parts)
                        ]
                    if matches:
                        path = matches[0]
                        break

            if not path.exists():
                return f"Error: File '{filepath_str}' does not exist."

    allowed_roots = _allowed_source_roots()
    try:
        resolved_path = path.resolve(strict=True)
    except OSError:
        return f"Error: Source file '{filepath_str}' could not be resolved."

    supported_source_suffixes = {".py", ".xml", ".csv", ".js", ".po", ".sql", ".css", ".scss", ".html"}
    is_allowed = any(
        resolved_path == root or root in resolved_path.parents
        for root in allowed_roots
    )
    if not is_allowed or not resolved_path.is_file() or resolved_path.suffix.lower() not in supported_source_suffixes:
        return "Error: Source file is outside configured addon roots or is not a supported source file."
    path = resolved_path

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
        except (OSError, UnicodeDecodeError) as err:
            _logger.warning("Cannot read %s to locate model %s: %s", path, target_model_resolved, err)

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

        body = "\n".join(snippet)
        from code_intelligence.rules.source_callees import (
            inspect_noop_hook_method,
            format_noop_hook_note,
        )
        hook_info = inspect_noop_hook_method("\n".join(selected_lines))
        if hook_info:
            func_name, noop_desc = hook_info
            body += "\n\n" + format_noop_hook_note(func_name, noop_desc)
        if include_citation:
            from code_intelligence.utils import format_file_link
            shown_start, shown_end = start_idx + 1, end_idx
            citation = format_file_link(str(path), shown_start, shown_end)
            body = f"Source: {citation}\n{body}"
        return body

    except Exception as e:
        _logger.error("Error reading file %s: %s", filepath_str, e)
        return f"Error reading file '{filepath_str}': {str(e)}"

# ── Introspection Tools ─────────────────────────────────────────────────

"""
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
    return resolve_technical_name_to_role(technical_name, _require_graph())


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
    return read_precise_source_code(filepath, line_start, line_end, include_citation=True)


@tool
def inspect_module_extensions(module_name: str) -> str:
    """Inspect native models extended by an Odoo module outside its own perimeter,
    including Python class names, source files, and added fields/methods."""
    from code_intelligence.rules.structure import (
        inspect_module_cross_domain_extensions,
        format_module_cross_domain_extensions,
    )
    G = _require_graph()
    extensions = inspect_module_cross_domain_extensions(G, module_name)
    return format_module_cross_domain_extensions(extensions, module_name)


__all__ = [
    "resolve_technical_name",
    "list_involved_modules",
    "explain_decision_path",
    "read_source_code",
    "inspect_module_extensions",
]
