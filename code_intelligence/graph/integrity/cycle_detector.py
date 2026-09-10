"""
code_intelligence/graph/cycle_detector.py

Inheritance cycle detection across Odoo models.
"""

import logging
from typing import Dict, List, Set

from ..nodes.models import ResolvedSymbolRegistry

_logger = logging.getLogger(__name__)


def _detect_inheritance_cycles(registry: ResolvedSymbolRegistry):
    """
    Detect inheritance cycles across models using visited: set().
    Fills registry.detected_cycles with detected cycle paths.
    Note: In-place model extensions (_inherit = 'model.name') where parent == model_name
    are excluded from cycle detection.
    """
    # Build model dependency graph excluding self-extensions (in-place module extensions)
    inheritance_graph: Dict[str, List[str]] = {}
    for model_name, decls in registry.models.items():
        parents = []
        for decl in decls:
            parents.extend(decl.inherit)
            parents.extend(decl.inherits.keys())
        # Exclude self-references (in-place _inherit = 'same.model')
        inheritance_graph[model_name] = [p for p in parents if p != model_name]

    visited: Set[str] = set()
    rec_stack: Set[str] = set()

    def dfs(node: str, path: List[str]):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for parent in inheritance_graph.get(node, []):
            if parent == node:
                continue
            if parent not in visited:
                dfs(parent, path)
            elif parent in rec_stack:
                cycle_start_idx = path.index(parent)
                cycle_path = path[cycle_start_idx:] + [parent]
                _logger.warning("Inheritance cycle detected: %s", " -> ".join(cycle_path))
                registry.detected_cycles.append(cycle_path)

        path.pop()
        rec_stack.remove(node)

    for model_name in list(inheritance_graph.keys()):
        if model_name not in visited:
            dfs(model_name, [])


__all__ = ["_detect_inheritance_cycles"]
