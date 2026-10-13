"""Project E1 candidate references onto the models they belong to (graph structure only)."""

from __future__ import annotations

from typing import Sequence

from .cards import CARD_NODE_TYPES, object_ref_of

_CHILD_OF_MODEL = frozenset({"Field", "Method", "Button"})


class ModelProjector:
    """Callable mapping a card reference to the references of its parent models.

    A model maps to itself; a field, method or button to the model that declares it;
    a menu to the models it opens; a record rule to the models it restricts. A reference
    without a parent model (a group, an unknown reference) maps to no model.
    """

    def __init__(self, graph):
        self._models_of: dict[str, tuple[str, ...]] = {}
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") not in CARD_NODE_TYPES:
                continue
            object_ref = object_ref_of(str(node_id), data)
            if object_ref:
                self._models_of[object_ref] = self._parent_models(graph, node_id, data)

    @staticmethod
    def _parent_models(graph, node_id, data) -> tuple[str, ...]:
        node_type = data.get("node_type")
        if node_type == "Model":
            return (object_ref_of(str(node_id), data),)
        if node_type in _CHILD_OF_MODEL:
            model = str(data.get("model") or "").strip()
            return (f"model:{model}",) if model else ()
        if node_type == "Menu":
            neighbours = (target for _, target, edge in graph.out_edges(node_id, data=True)
                          if edge.get("edge_type") == "OPENS_MODEL")
        elif node_type == "Rule":
            neighbours = (source for source, _, edge in graph.in_edges(node_id, data=True)
                          if edge.get("edge_type") == "RESTRICTED_BY")
        else:
            return ()
        refs = (object_ref_of(str(neighbour), graph.nodes[neighbour]) for neighbour in neighbours)
        return tuple(dict.fromkeys(ref for ref in refs if ref))

    def __call__(self, object_ref: str) -> tuple[str, ...]:
        if object_ref.startswith("model:"):
            return (object_ref,)
        return self._models_of.get(object_ref, ())


def project_candidates(candidates: Sequence[str], projector: ModelProjector) -> list[str]:
    """Models of the candidates in rank order, each model kept at its best rank."""
    return list(dict.fromkeys(model for ref in candidates for model in projector(ref)))
