"""Helper functions, state guards, and prioritization logic for CI agent tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.utils import SENSITIVE_BYPASS_MARKER, format_file_link
import re

_logger = logging.getLogger(__name__)
_GRAPH_REF = None
_LLM_REF = None
_CURRENT_QUESTION = None


def set_graph_ref(G):
    """Set global knowledge graph reference for tool wrappers."""
    global _GRAPH_REF
    _GRAPH_REF = G


def get_graph_ref():
    return _GRAPH_REF


def set_llm_ref(llm):
    """Set global LLM reference for tool wrappers."""
    global _LLM_REF
    _LLM_REF = llm


def get_llm_ref():
    return _LLM_REF


def set_current_question(question: Optional[str]):
    """Set the current question used by tool-internal relevance ranking."""
    global _CURRENT_QUESTION
    _CURRENT_QUESTION = question


def get_current_question() -> Optional[str]:
    return _CURRENT_QUESTION


def _require_graph():
    if _GRAPH_REF is None:
        raise RuntimeError("Knowledge graph not initialized. Call set_graph_ref(G) first.")
    return _GRAPH_REF


WILDCARD_MODEL_ERROR_MSG = (
    "Erreur : le modèle doit être spécifié explicitement (les jokers '*' et "
    "l'extraction globale de tous les modèles ne sont pas autorisés par la politique de sécurité J32-J33)."
)


def _is_wildcard_model(model_name: str) -> bool:
    clean = (model_name or "").strip().lower()
    return clean in {"*", "%", "all", "tous", "tous les modèles", "all models", ""}


def _resolve_model_param(model_name: str) -> str:
    """Resolve model param to technical model identifier if possible."""
    if _is_wildcard_model(model_name):
        return model_name
    G = _require_graph()
    if G.has_node(f"model:{model_name}"):
        return model_name
    concept = resolve_business_term(model_name, G)
    if concept.is_resolved and len(concept.resolved_models) == 1:
        _logger.info("Resolved business term %r -> %r", model_name, concept.resolved_models[0])
        return concept.resolved_models[0]
    return model_name


resolve_model_param = _resolve_model_param


def find_model_source_filepaths(G, model_name: str) -> set:
    model_node = f"model:{model_name}"
    if model_node not in G:
        return set()
    filepaths = set(G.nodes[model_node].get("filepaths", []))
    for u, v, attrs in G.edges(data=True):
        if attrs.get("edge_type") == "HAS_FIELD" and u == model_node:
            f_path = G.nodes[v].get("filepath", "")
            if f_path:
                filepaths.add(f_path)
    for node, attrs in G.nodes(data=True):
        if attrs.get("node_type") == "Method" and attrs.get("model") == model_name:
            f_path = attrs.get("filepath", "")
            if f_path:
                filepaths.add(f_path)
    for _, target_node, attrs in G.out_edges(model_node, data=True):
        if attrs.get("edge_type") == "EXTENDS" and target_node.startswith("model:"):
            filepaths.update(G.nodes[target_node].get("filepaths", []))
    return filepaths


def find_security_lock_source_files(G, model_name: str) -> list:
    from code_intelligence.rules.security import python_source_has_security_findings
    filepaths = find_model_source_filepaths(G, model_name)
    hit_files = []
    for fp in sorted(filepaths):
        if not _is_custom_module_filepath(fp):
            continue
        p = Path(fp)
        if not p.exists():
            continue
        code = p.read_text(encoding="utf-8")
        if python_source_has_security_findings(code, fp):
            hit_files.append(fp)
    return hit_files


def find_server_action_nodes(G, model_name: str) -> list:
    """Use resolved model targets, never re-infer XML references at query time."""
    modelNode = f"model:{model_name}"
    if modelNode not in G or G.nodes[modelNode].get("node_type") != "Model":
        return []
    actions = []
    for node, attrs in G.nodes(data=True):
        if attrs.get("node_type") != "ServerAction":
            continue
        targetEdge = G.get_edge_data(node, modelNode) or {}
        if attrs.get("target_model") == model_name or targetEdge.get("edge_type") == "TARGETS_MODEL":
            actions.append((node, attrs))
    return actions


def find_methods_with_override_cascade(G, model_name: str) -> list:
    prefix = f"method:{model_name}."
    method_names = []
    for node, attrs in G.nodes(data=True):
        if not node.startswith(prefix):
            continue
        if attrs.get("node_type") != "Method":
            continue
        if len(attrs.get("override_sites", [])) > 1:
            method_names.append(node[len(prefix):])
    return method_names


def _is_custom_module_filepath(filepath: str) -> bool:
    from config.settings import (
        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS,
    )
    try:
        resolved = Path(filepath).resolve()
        if any(root and Path(root).resolve() in resolved.parents for root in dict.fromkeys((CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS))):
            return True
        if CORE_ADDONS_PATH and Path(CORE_ADDONS_PATH).resolve() in resolved.parents:
            return False
        if CORE_FRAMEWORK_ADDONS_PATH and Path(CORE_FRAMEWORK_ADDONS_PATH).resolve() in resolved.parents:
            return False
    except (OSError, RuntimeError) as err:
        _logger.warning("Cannot resolve path %s: %s", filepath, err)
    path_parts = Path(filepath).parts
    core_dirs = {"odoo/addons", "base", "web"}
    if any(c in path_parts for c in core_dirs):
        return False
    return True


def _is_custom_server_action_module(G, xml_id: str) -> bool:
    if "." not in xml_id:
        return False
    module_node = f"module:{xml_id.split('.', 1)[0]}"
    if module_node not in G:
        return False
    module_filepath = G.nodes[module_node].get("filepath", "")
    if not module_filepath:
        return False
    return _is_custom_module_filepath(module_filepath)


def _sort_server_action_entries_custom_first(entries: list) -> list:
    def _priority(entry):
        xml_id, is_custom, summary = entry
        has_bypass_marker = SENSITIVE_BYPASS_MARKER in summary
        return (not (is_custom or has_bypass_marker), xml_id)
    return sorted(entries, key=_priority)


def _sort_filepaths_custom_first(filepaths) -> list:
    return sorted(filepaths, key=lambda fp: (not _is_custom_module_filepath(fp), fp))


def _trace_invoked_methods_with_citations(G, model_name: str, code: str):
    """Trace direct and nested calls, retaining structured source citations."""
    invoked_methods = re.findall(r"\b(?:model|records?|self)\.([a-zA-Z0-9_]+)\s*\(", code)
    lines = []
    citations = []
    for m_name in invoked_methods:
        m_node_id = f"method:{model_name}.{m_name}"
        if m_node_id not in G:
            continue
        m_attrs = G.nodes[m_node_id]
        m_fp = m_attrs.get("filepath")
        m_start = m_attrs.get("lineno", 1)
        m_end = m_attrs.get("end_lineno") or (m_start + 30)
        if m_fp:
            m_link = format_file_link(m_fp, m_start, m_end)
            lines.append(f"\n  - Python method called: {m_name}() (Defined at {m_link})")
            citations.append((m_fp, m_start, m_end))
            queue = [(m_name, m_fp, m_start, m_end, 1)]
            visited_m = {m_name}
            while queue:
                curr_m, curr_fp, curr_start, curr_end, depth = queue.pop(0)
                if depth > 2:
                    break
                try:
                    p = Path(curr_fp)
                    if p.exists():
                        src_lines = p.read_text(encoding="utf-8").splitlines()
                        curr_code = "\n".join(src_lines[max(0, curr_start - 1):min(len(src_lines), curr_end)])
                        sub_calls = re.findall(r"\b(?:obj|self|record)\.([a-zA-Z0-9_]+)\s*\(", curr_code)
                        for sub_m in sub_calls:
                            if sub_m in visited_m:
                                continue
                            visited_m.add(sub_m)
                            sub_node_id = f"method:{model_name}.{sub_m}"
                            if sub_node_id in G:
                                sub_attrs = G.nodes[sub_node_id]
                                sub_fp = sub_attrs.get("filepath")
                                sub_start = sub_attrs.get("lineno", 1)
                                sub_end = sub_attrs.get("end_lineno") or (sub_start + 30)
                                if sub_fp:
                                    sub_link = format_file_link(sub_fp, sub_start, sub_end)
                                    indent = "  " * depth
                                    lines.append(f"\n{indent}  -> Sub-method called: {sub_m}() (Defined at {sub_link})")
                                    citations.append((sub_fp, sub_start, sub_end))
                                    queue.append((sub_m, sub_fp, sub_start, sub_end, depth + 1))
                except (OSError, UnicodeDecodeError) as err:
                    _logger.warning("Cannot read %s while following sub-methods: %s", curr_fp, err)
    return "".join(lines), citations


def _trace_invoked_methods(G, model_name: str, code: str) -> str:
    return _trace_invoked_methods_with_citations(G, model_name, code)[0]
