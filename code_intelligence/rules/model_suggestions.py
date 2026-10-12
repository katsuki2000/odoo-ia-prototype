"""Closest indexed models for a model name that is absent from the graph."""

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import List, Set

import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER

DEFAULT_SUGGESTION_LIMIT = 5
RETRY_INSTRUCTION = (
    "If one of these matches the question, call the same tool again with that exact model name "
    "instead of answering."
)
_MODEL_NODE_PREFIX = "model:"
_TOKEN_SPLIT_RE = re.compile(r"[._\s-]+")


def _tokens(model_name: str) -> Set[str]:
    return {token for token in _TOKEN_SPLIT_RE.split(model_name.lower()) if token}


def _indexed_model_names(G: nx.DiGraph) -> List[str]:
    return [
        node_id[len(_MODEL_NODE_PREFIX):]
        for node_id, data in G.nodes(data=True)
        if data.get("node_type") == "Model" and node_id.startswith(_MODEL_NODE_PREFIX)
    ]


def closest_models(G: nx.DiGraph, model_name: str, limit: int = DEFAULT_SUGGESTION_LIMIT) -> List[str]:
    """Rank indexed models by rarity-weighted token overlap with ``model_name``.

    A shared token weighs more when few models carry it, so a distinctive
    word outranks a prefix such as ``res`` or ``account``. Ties fall back to
    character-sequence similarity, then to the name for a stable order.
    """
    query_tokens = _tokens(model_name)
    names = _indexed_model_names(G)
    if not query_tokens or not names or limit <= 0:
        return []

    model_tokens = {name: _tokens(name) for name in names}
    document_frequency = Counter(token for tokens in model_tokens.values() for token in tokens)

    def weight(token: str) -> float:
        return math.log(1 + len(names) / max(document_frequency[token], 1))

    scored = []
    for name, tokens in model_tokens.items():
        shared = query_tokens & tokens
        if not shared:
            continue
        overlap = sum(weight(token) for token in shared)
        union = sum(weight(token) for token in query_tokens | tokens)
        similarity = SequenceMatcher(None, model_name.lower(), name).ratio()
        scored.append((-overlap / union, -similarity, name))

    scored.sort()
    return [name for _, _, name in scored[:limit]]


def model_not_found_message(G: nx.DiGraph, model_name: str, limit: int = DEFAULT_SUGGESTION_LIMIT) -> str:
    message = f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
    candidates = closest_models(G, model_name, limit)
    if not candidates:
        return message
    return f"{message} Closest indexed models by name: {', '.join(candidates)}. {RETRY_INSTRUCTION}"
