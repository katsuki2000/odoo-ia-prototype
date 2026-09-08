"""
code_intelligence/graph/topological_sort.py

Topological sort for Odoo module dependency resolution.
"""

import logging
from typing import Dict, List, Set

from .models import ParsedModule

_logger = logging.getLogger(__name__)


def topological_sort_modules(modules_dict: Dict[str, ParsedModule]) -> List[str]:
    """
    Topologically sort module names based on manifest 'depends'.
    Ensures parent modules are indexed before dependent modules.
    """
    sorted_modules: List[str] = []
    visited: Set[str] = set()

    def visit(m_name: str, chain: List[str]):
        if m_name in chain:
            _logger.warning("Circular dependency detected in manifests: %s", " -> ".join(chain + [m_name]))
            return
        if m_name not in visited:
            visited.add(m_name)
            mod = modules_dict.get(m_name)
            if mod and mod.manifest:
                for dep in mod.manifest.depends:
                    visit(dep, chain + [m_name])
            elif mod is not None:
                _logger.warning(
                    "Module '%s' has no manifest (or no manifest.depends) -- "
                    "treating it as having NO dependencies for load-order "
                    "purposes. If '%s' actually depends on other modules, this "
                    "will silently produce a wrong load_order and a wrong "
                    "method-override execution order for any method it shares "
                    "with those dependencies.",
                    m_name, m_name,
                )
            sorted_modules.append(m_name)

    for name in modules_dict:
        visit(name, [])

    return sorted_modules


__all__ = ["topological_sort_modules"]
