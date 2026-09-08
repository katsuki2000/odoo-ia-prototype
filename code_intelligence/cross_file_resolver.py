"""
code_intelligence/cross_file_resolver.py

Backward-compatible facade for cross-file symbol resolution.
All implementations have moved to `code_intelligence.graph`.
"""

from code_intelligence.graph.cycle_detector import _detect_inheritance_cycles
from code_intelligence.graph.models import (
    CORE_BASE_MODULES,
    ParsedModule,
    ResolvedSymbolRegistry,
    UnresolvedCategory,
    UnresolvedReference,
)
from code_intelligence.graph.symbol_merger import (
    _merge_action,
    _merge_group,
    _merge_rule,
    _merge_server_action,
)
from code_intelligence.graph.symbol_resolver import (
    _categorize_unresolved,
    _resolve_group_reference,
    _resolve_model_reference,
    build_module_symbol_registry,
)
from code_intelligence.graph.topological_sort import topological_sort_modules

__all__ = [
    "UnresolvedCategory",
    "UnresolvedReference",
    "ParsedModule",
    "ResolvedSymbolRegistry",
    "CORE_BASE_MODULES",
    "topological_sort_modules",
    "build_module_symbol_registry",
    "_resolve_model_reference",
    "_resolve_group_reference",
    "_categorize_unresolved",
    "_detect_inheritance_cycles",
    "_merge_action",
    "_merge_server_action",
    "_merge_rule",
    "_merge_group",
]
