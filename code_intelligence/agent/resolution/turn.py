"""One resolution decision per question/graph snapshot, shared by routing and CI."""

import hashlib
import json
import os
import weakref
from copy import deepcopy
from threading import RLock

from .matching import ResolvedConcept, _FUZZY_INDEX_CACHE
from .candidates import _TIEBREAK_RARITY_CACHE

_GRAPH_VERSIONS = weakref.WeakKeyDictionary()
_LOCK = RLock()
TURN_KEY = 'resolution_turn'


class LazyArbitrationClient:
    def __init__(self):
        self.client = None

    def invoke(self, messages):
        if self.client is None:
            from core.llm.llm_client import get_chat_llm
            self.client = get_chat_llm(temperature=0.0, max_retries=0, max_tokens=1024)
        return self.client.invoke(messages)


def _graph_version(graph):
    if graph is None:
        return 'unavailable'
    nodes = sorted((nodeId, {key: data.get(key) for key in
                    ('node_type', 'name', 'label', 'description', 'model', 'business_labels')})
                   for nodeId, data in graph.nodes(data=True))
    edges = sorted((source, target, data.get('edge_type'), data.get('role'))
                   for source, target, data in graph.edges(data=True))
    version = hashlib.sha256(json.dumps([nodes, edges], sort_keys=True, default=str).encode()).hexdigest()
    with _LOCK:
        if _GRAPH_VERSIONS.get(graph) != version:
            _FUZZY_INDEX_CACHE.pop(graph, None)
            _TIEBREAK_RARITY_CACHE.pop(graph, None)
            _GRAPH_VERSIONS[graph] = version
    return version


def resolve_turn(question, graph, state, *, language=None, llm=None):
    from .resolver import resolve_business_term
    configuration = {key: value for key, value in os.environ.items()
                     if key.startswith(('AWS_', 'KAGGLE_')) or key == 'LLM_TARGET'}
    history = [(getattr(message, 'type', ''), getattr(message, 'content', str(message)))
               for message in state.get('chat_history', [])]
    signature = hashlib.sha256(json.dumps([question.strip(), language, id(graph), _graph_version(graph),
                                           configuration, history], sort_keys=True, default=str).encode()).hexdigest()
    cached = state.get('resolved_concept')
    if isinstance(cached, dict) and (cached.get('diagnostics') or {}).get(TURN_KEY) == signature:
        try:
            return ResolvedConcept(**deepcopy(cached)), True
        except TypeError:
            pass
    concept = resolve_business_term(question, graph, llm=llm if llm is not None else LazyArbitrationClient(), language=language)
    concept.diagnostics[TURN_KEY] = signature
    return concept, False
