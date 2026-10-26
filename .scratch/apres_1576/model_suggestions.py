"""Closest indexed models or modules for a name that is absent from the graph."""

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import List, Set

import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER

DEFAULT_SUGGESTION_LIMIT = 5
_RETRY_TEMPLATE = (
    "If one of these matches the question, call the same tool again with that exact {kind} name "
    "instead of answering."
)
RETRY_INSTRUCTION = _RETRY_TEMPLATE.format(kind="model")
_TOKEN_SPLIT_RE = re.compile(r"[._\s-]+")


def _tokens(name: str) -> Set[str]:
    return {token for token in _TOKEN_SPLIT_RE.split(name.lower()) if token}


def _indexed_names(G: nx.DiGraph, node_type: str) -> List[str]:
    """Names of the nodes of one type; node ids are `<node_type lowercased>:<name>`."""
    prefix = f"{node_type.lower()}:"
    return [
        node_id[len(prefix):]
        for node_id, data in G.nodes(data=True)
        if data.get("node_type") == node_type and node_id.startswith(prefix)
    ]


def _closest(G: nx.DiGraph, name: str, node_type: str, limit: int) -> List[str]:
    """Rank indexed names by rarity-weighted token overlap with ``name``.

    A shared token weighs more when few names carry it, so a distinctive
    word outranks a prefix such as ``res`` or ``account``. Ties fall back to
    character-sequence similarity, then to the name for a stable order.
    """
    query_tokens = _tokens(name)
    names = _indexed_names(G, node_type)
    if not query_tokens or not names or limit <= 0:
        return []

    name_tokens = {candidate: _tokens(candidate) for candidate in names}
    document_frequency = Counter(token for tokens in name_tokens.values() for token in tokens)

    def weight(token: str) -> float:
        return math.log(1 + len(names) / max(document_frequency[token], 1))

    scored = []
    for candidate, tokens in name_tokens.items():
        shared = query_tokens & tokens
        if not shared:
            continue
        overlap = sum(weight(token) for token in shared)
        union = sum(weight(token) for token in query_tokens | tokens)
        similarity = SequenceMatcher(None, name.lower(), candidate).ratio()
        scored.append((-overlap / union, -similarity, candidate))

    scored.sort()
    return [candidate for _, _, candidate in scored[:limit]]


def closest_models(G: nx.DiGraph, model_name: str, limit: int = DEFAULT_SUGGESTION_LIMIT) -> List[str]:
    return _closest(G, model_name, "Model", limit)


def closest_modules(G: nx.DiGraph, module_name: str, limit: int = DEFAULT_SUGGESTION_LIMIT) -> List[str]:
    return _closest(G, module_name, "Module", limit)


def _not_found_message(kind: str, name: str, hint: str, candidates: List[str]) -> str:
    message = f"{kind.capitalize()} '{name}' {NOT_FOUND_MARKER} ({hint})."
    if not candidates:
        return message
    return (
        f"{message} Closest indexed {kind}s by name: {', '.join(candidates)}. "
        f"{_RETRY_TEMPLATE.format(kind=kind)}"
    )


def model_not_found_message(G: nx.DiGraph, model_name: str, limit: int = DEFAULT_SUGGESTION_LIMIT) -> str:
    return _not_found_message(
        "model", model_name, "probable typo or missing model", closest_models(G, model_name, limit))


def module_not_found_message(G: nx.DiGraph, module_name: str, limit: int = DEFAULT_SUGGESTION_LIMIT) -> str:
    return _not_found_message(
        "module", module_name, "probable typo or module not installed", closest_modules(G, module_name, limit))
