"""Knowledge graph package for Code Intelligence."""

from .builder import OdooGraphBuilder, _humanize_technical_name
from .integrity import (
    _detect_inheritance_cycles,
    topological_sort_modules,
    IncrementalEvent,
    IncrementalEventLogger,
    record_incremental_update,
    LATENCY_BUDGET_PARTIAL_RECALC_SECONDS,
)
from .loader import (
    _graph_filepaths_resolve_locally,
    _load_module,
    get_code_intelligence_graph as _get_legacy_graph,
    GRAPH_JSON_PATH,
    _CACHED_CODE_INTEL_GRAPH,
    _CACHED_GRAPH_MTIME,
)
from .nodes import (
    ParsedModule,
    ResolvedSymbolRegistry,
    UnresolvedCategory,
    UnresolvedReference,
    CORE_BASE_MODULES,
)
from .serialization import (
    save_graph_to_json,
    load_graph_from_json,
    benchmark_graph_traversal,
)
from .symbols import (
    _merge_action,
    _merge_group,
    _merge_rule,
    _merge_server_action,
    _categorize_unresolved,
    _resolve_group_reference,
    _resolve_model_reference,
    build_module_symbol_registry,
    SymbolRename,
    detect_model_renames,
    refactor_rename_in_graph,
)
from .staleness import (
    StalenessLevel,
    StalenessReport,
    compute_file_hash,
    build_file_hash_index,
    analyze_changes,
)
from .atomic_swap import atomic_write_json, atomic_read_json
from .version import (
    GRAPH_SCHEMA_VERSION,
    get_git_commit_hash,
    build_graph_metadata,
    serialize_graph_with_metadata,
    deserialize_graph_with_metadata,
)


def get_code_intelligence_graph(**kwargs):
    import os
    path = os.getenv('CI_RUNTIME_GRAPH_PATH', '').strip()
    if path:
        from .runtime_graph import load_runtime_graph
        return load_runtime_graph(path, os.getenv('CI_RUNTIME_GRAPH_INSTANCE', '').strip())
    return _get_legacy_graph(**kwargs)
