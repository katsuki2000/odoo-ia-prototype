"""Replace the technical identifiers known to the graph by their business labels in the final answer."""

import re
import weakref
from typing import Dict, Optional, Tuple

import networkx as nx

from code_intelligence.agent.node_labels import node_labels

_INDEX_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _labels_by_identifier(G: nx.DiGraph) -> Dict[str, str]:
    labels = {}
    for _, data in G.nodes(data=True):
        for action in data.get('window_actions', ()):
            labels[action['xml_id']] = action.get('name', '')
        identifier = data.get('name') if data.get('node_type') == 'Model' else data.get('xml_id')
        if identifier:
            labels[identifier] = ' / '.join(node_labels(data))
    return {identifier: label for identifier, label in labels.items() if label and label != identifier}


def _index(G: nx.DiGraph) -> Tuple[Dict[str, str], "re.Pattern"]:
    if G not in _INDEX_CACHE:
        labels = _labels_by_identifier(G)
        alternatives = '|'.join(re.escape(identifier) for identifier in sorted(labels, key=len, reverse=True))
        _INDEX_CACHE[G] = labels, re.compile(rf'`?(?<![\w.])({alternatives})(?!\w|\.\w)`?')
    return _INDEX_CACHE[G]


def replace_technical_identifiers(answer: str, G: Optional[nx.DiGraph]) -> str:
    if G is None:
        return answer
    labels, pattern = _index(G)
    return pattern.sub(lambda match: labels[match.group(1)], answer) if labels else answer
