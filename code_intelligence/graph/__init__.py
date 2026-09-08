"""
code_intelligence/graph/__init__.py

Central package for Odoo Knowledge Graph construction, resolution, and caching.
"""

from .builder import OdooGraphBuilder, _humanize_technical_name
from .cycle_detector import _detect_inheritance_cycles
from .disk_loader import _graph_filepaths_resolve_locally, _load_module
from .loader import GRAPH_JSON_PATH, get_code_intelligence_graph
from .models import (
    CORE_BASE_MODULES,
    ParsedModule,
    ResolvedSymbolRegistry,
    UnresolvedCategory,
    UnresolvedReference,
)
from .serialization import (
    benchmark_graph_traversal,
    load_graph_from_json,
    save_graph_to_json,
)
from .symbol_merger import (
    _merge_action,
    _merge_group,
    _merge_rule,
    _merge_server_action,
)
from .symbol_resolver import (
    _categorize_unresolved,
    _resolve_group_reference,
    _resolve_model_reference,
    build_module_symbol_registry,
)
from .topological_sort import topological_sort_modules

__all__ = [
    # Models
    "ParsedModule",
    "ResolvedSymbolRegistry",
    "UnresolvedCategory",
    "UnresolvedReference",
    "CORE_BASE_MODULES",
    # Builders & Serialization
    "OdooGraphBuilder",
    "_humanize_technical_name",
    "save_graph_to_json",
    "load_graph_from_json",
    "benchmark_graph_traversal",
    # Resolver & Sort
    "build_module_symbol_registry",
    "topological_sort_modules",
    "_detect_inheritance_cycles",
    "_resolve_model_reference",
    "_resolve_group_reference",
    "_categorize_unresolved",
    # Mergers
    "_merge_action",
    "_merge_server_action",
    "_merge_rule",
    "_merge_group",
    # Loaders
    "get_code_intelligence_graph",
    "GRAPH_JSON_PATH",
    "_load_module",
    "_graph_filepaths_resolve_locally",
]
