"""
code_intelligence/graph/__init__.py

Central package for Odoo Knowledge Graph construction, resolution, and caching.
"""

from .builder import OdooGraphBuilder, _humanize_technical_name
from .cycle_detector import _detect_inheritance_cycles
from .disk_loader import _graph_filepaths_resolve_locally, _load_module
from .loader import (
    GRAPH_JSON_PATH,
    get_code_intelligence_graph,
    _CACHED_CODE_INTEL_GRAPH,
    _CACHED_GRAPH_MTIME,
)
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

from .staleness_models import (
    StalenessLevel,
    StalenessReport,
    compute_file_hash,
    build_file_hash_index,
)
from .staleness_detector import (
    GraphStalenessDetector,
    analyze_changes,
)

from .atomic_swap import atomic_write_json, atomic_read_json
from .symbol_refactor import SymbolRename, detect_model_renames, refactor_rename_in_graph
from .version import (
    GRAPH_SCHEMA_VERSION,
    get_git_commit_hash,
    build_graph_metadata,
    serialize_graph_with_metadata,
    deserialize_graph_with_metadata,
)
from .event_logger import (
    IncrementalEvent,
    IncrementalEventLogger,
    record_incremental_update,
    LATENCY_BUDGET_PARTIAL_RECALC_SECONDS,
)

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
    "_CACHED_CODE_INTEL_GRAPH",
    "_CACHED_GRAPH_MTIME",
    "_load_module",
    "_graph_filepaths_resolve_locally",
    # Staleness
    "StalenessLevel",
    "StalenessReport",
    "compute_file_hash",
    "build_file_hash_index",
    "GraphStalenessDetector",
    "analyze_changes",
    # Atomic Swap
    "atomic_write_json",
    "atomic_read_json",
    # Symbol Refactor
    "SymbolRename",
    "detect_model_renames",
    "refactor_rename_in_graph",
    # Versioning
    "GRAPH_SCHEMA_VERSION",
    "get_git_commit_hash",
    "build_graph_metadata",
    "serialize_graph_with_metadata",
    "deserialize_graph_with_metadata",
    # Event Logger
    "IncrementalEvent",
    "IncrementalEventLogger",
    "record_incremental_update",
    "LATENCY_BUDGET_PARTIAL_RECALC_SECONDS",
]
