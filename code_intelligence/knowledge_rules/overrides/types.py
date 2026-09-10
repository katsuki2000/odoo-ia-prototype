"""Data classes and graph resolution for method override chains."""

from dataclasses import dataclass, field
from typing import List, Optional

import networkx as nx

from core.evidence.evidence import Evidence


@dataclass
class MethodOverrideSite:
    """One module's override of a given method in execution order."""
    module: str
    filepath: str
    lineno: int
    end_lineno: Optional[int] = None


@dataclass
class MethodOverrideChainResult:
    """Composed override-chain analysis summary and associated evidence."""
    summary_text: str
    evidence: List[Evidence] = field(default_factory=list)


def resolve_method_override_chain(
    G: nx.DiGraph, model_name: str, method_name: str
) -> List[MethodOverrideSite]:
    """Return every module overriding the given method in execution order."""
    method_node_id = f"method:{model_name}.{method_name}"
    if method_node_id not in G:
        return []

    raw_sites = G.nodes[method_node_id].get("override_sites", [])
    sites = [
        MethodOverrideSite(
            module=s.get("module", "unknown"),
            filepath=s.get("filepath", ""),
            lineno=s.get("lineno", 0),
            end_lineno=s.get("end_lineno"),
        )
        for s in raw_sites
    ]
    return list(reversed(sites))
