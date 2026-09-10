"""
core/graph/__init__.py

Regroupement (todo/contexte.txt Section 649-653) : graph_nodes.py, graph_compat.py, graph.py.
"""

from .graph_nodes import (
    logger,
    smalltalk_gate,
    smalltalk_decision,
    out_of_scope_gate,
    out_of_scope_decision,
    retrieve,
    format_output,
    ci_evidence_decision,
)
from .graph import (
    __getattr__,
    build_graph,
    query_graph,
)

__all__ = [
    "logger",
    "smalltalk_gate",
    "smalltalk_decision",
    "out_of_scope_gate",
    "out_of_scope_decision",
    "retrieve",
    "format_output",
    "ci_evidence_decision",
    "__getattr__",
    "build_graph",
    "query_graph",
]
