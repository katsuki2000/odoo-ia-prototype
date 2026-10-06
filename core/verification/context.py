import weakref
from dataclasses import dataclass
from functools import cached_property
from typing import Any, FrozenSet, Iterable, Optional, Tuple

import networkx as nx

from core.verification.base_methods import BUILTIN_NAMES
from core.verification.extractors import find_number_tokens

_METHOD_NAMES_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def flatten_numeric_values(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from flatten_numeric_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from flatten_numeric_values(item)


def graph_method_names(graph: nx.DiGraph) -> FrozenSet[str]:
    cached = _METHOD_NAMES_CACHE.get(graph)
    if cached is None:
        cached = frozenset(
            attrs["name"]
            for _node, attrs in graph.nodes(data=True)
            if attrs.get("node_type") == "Method" and attrs.get("name")
        )
        _METHOD_NAMES_CACHE[graph] = cached
    return cached


@dataclass
class VerificationContext:
    texts: Tuple[str, ...] = ()
    numeric_values: Tuple[float, ...] = ()
    graph: Optional[nx.DiGraph] = None
    base_methods: FrozenSet[str] = frozenset()

    @cached_property
    def evidence_text(self) -> str:
        return "\n".join(self.texts)

    @cached_property
    def evidence_numbers(self) -> Tuple[float, ...]:
        from_text = (
            reading.value
            for token in find_number_tokens(self.evidence_text)
            for reading in token.readings
        )
        return tuple(self.numeric_values) + tuple(from_text)

    @cached_property
    def native_method_names(self) -> FrozenSet[str]:
        return BUILTIN_NAMES | self.base_methods

    @cached_property
    def graph_method_names(self) -> FrozenSet[str]:
        return graph_method_names(self.graph) if self.graph is not None else frozenset()
