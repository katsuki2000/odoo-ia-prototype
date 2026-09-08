"""
code_intelligence/graph_builder.py

Backward-compatible facade for Knowledge Graph building and serialization.
All implementations have moved to `code_intelligence.graph`.
"""

from code_intelligence.graph.builder import (
    OdooGraphBuilder,
    _humanize_technical_name,
)
from code_intelligence.graph.serialization import (
    benchmark_graph_traversal,
    load_graph_from_json,
    save_graph_to_json,
)

__all__ = [
    "OdooGraphBuilder",
    "_humanize_technical_name",
    "save_graph_to_json",
    "load_graph_from_json",
    "benchmark_graph_traversal",
]
