"""
code_intelligence/ci_graph_loader.py

Backward-compatible facade for Knowledge Graph loading and caching.
All implementations have moved to `code_intelligence.graph`.
"""

from code_intelligence.graph.disk_loader import (
    _graph_filepaths_resolve_locally,
    _load_module,
)
from code_intelligence.graph.loader import (
    GRAPH_JSON_PATH,
    _CACHED_CODE_INTEL_GRAPH,
    _CACHED_GRAPH_MTIME,
    get_code_intelligence_graph,
)

__all__ = [
    "get_code_intelligence_graph",
    "GRAPH_JSON_PATH",
    "_load_module",
    "_graph_filepaths_resolve_locally",
    "_CACHED_CODE_INTEL_GRAPH",
    "_CACHED_GRAPH_MTIME",
]
