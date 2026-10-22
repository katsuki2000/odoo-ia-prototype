"""Shared request state and graph helpers for CI tools."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from code_intelligence.agent.resolution.resolver import resolve_business_term

_logger = logging.getLogger(__name__)
_graphRef = ContextVar('ci_graph', default=None)
_llmRef = ContextVar('ci_llm', default=None)
_currentQuestion = ContextVar('ci_question', default=None)

WILDCARD_MODEL_ERROR_MSG = (
    "Erreur : le modèle doit être spécifié explicitement ; "
    "l'extraction globale de tous les modèles n'est pas autorisée."
)


def set_graph_ref(graph):
    _graphRef.set(graph)


def get_graph_ref():
    return _graphRef.get()


def set_llm_ref(llm):
    _llmRef.set(llm)


def get_llm_ref():
    return _llmRef.get()


def get_current_question() -> Optional[str]:
    return _currentQuestion.get()


@contextmanager
def tool_context(graph, llm, question):
    graphToken = _graphRef.set(graph)
    llmToken = _llmRef.set(llm)
    questionToken = _currentQuestion.set(question)
    try:
        yield
    finally:
        _currentQuestion.reset(questionToken)
        _llmRef.reset(llmToken)
        _graphRef.reset(graphToken)


def _require_graph():
    graph = get_graph_ref()
    if graph is None:
        raise RuntimeError('Knowledge graph not initialized.')
    return graph


def _is_wildcard_model(model_name: str) -> bool:
    return (model_name or '').strip().lower() in {
        '*', '%', 'all', 'tous', 'tous les modèles', 'all models', '',
    }


def _resolve_model_param(model_name: str) -> str:
    if _is_wildcard_model(model_name):
        return model_name
    graph = _require_graph()
    if graph.has_node(f'model:{model_name}'):
        return model_name
    concept = resolve_business_term(model_name, graph)
    if concept.is_resolved and len(concept.resolved_models) == 1:
        return concept.resolved_models[0]
    return model_name


def find_model_source_filepaths(graph, model_name: str) -> set[str]:
    modelNode = f'model:{model_name}'
    if modelNode not in graph:
        return set()
    paths = set(graph.nodes[modelNode].get('filepaths', []))
    for source, target, edge in graph.edges(data=True):
        if source == modelNode and edge.get('edge_type') == 'HAS_FIELD':
            filepath = graph.nodes[target].get('filepath')
            if filepath:
                paths.add(filepath)
    for _, attributes in graph.nodes(data=True):
        if attributes.get('node_type') == 'Method' and attributes.get('model') == model_name:
            filepath = attributes.get('filepath')
            if filepath:
                paths.add(filepath)
    for _, target, edge in graph.out_edges(modelNode, data=True):
        if edge.get('edge_type') == 'EXTENDS' and target.startswith('model:'):
            paths.update(graph.nodes[target].get('filepaths', []))
    return paths


def find_server_action_nodes(graph, model_name: str) -> list[tuple[str, dict]]:
    modelNode = f'model:{model_name}'
    if modelNode not in graph or graph.nodes[modelNode].get('node_type') != 'Model':
        return []
    actions = []
    for node, attributes in graph.nodes(data=True):
        if attributes.get('node_type') != 'ServerAction':
            continue
        edge = graph.get_edge_data(node, modelNode) or {}
        if attributes.get('target_model') == model_name or edge.get('edge_type') == 'TARGETS_MODEL':
            actions.append((node, attributes))
    return actions


def _is_custom_module_filepath(filepath: str) -> bool:
    from config.settings import (
        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS,
    )

    try:
        resolved = Path(filepath).resolve()
        customRoots = [
            Path(root).resolve()
            for root in (CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS)
            if root
        ]
        if any(root == resolved or root in resolved.parents for root in customRoots):
            return True
        coreRoots = [
            Path(root).resolve()
            for root in (CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH)
            if root
        ]
        return not any(root == resolved or root in resolved.parents for root in coreRoots)
    except (OSError, RuntimeError) as error:
        _logger.warning('Cannot resolve path %s: %s', filepath, error)
        return True


def _is_custom_server_action_module(graph, xml_id: str) -> bool:
    if '.' not in xml_id:
        return False
    moduleNode = f'module:{xml_id.split(".", 1)[0]}'
    filepath = graph.nodes[moduleNode].get('filepath', '') if moduleNode in graph else ''
    return bool(filepath and _is_custom_module_filepath(filepath))


def _sort_server_action_entries_custom_first(entries: list) -> list:
    return sorted(entries, key=lambda entry: (not entry[1], entry[0]))


def _sort_filepaths_custom_first(filepaths) -> list:
    return sorted(filepaths, key=lambda filepath: (not _is_custom_module_filepath(filepath), filepath))
