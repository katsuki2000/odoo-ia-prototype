"""
code_intelligence/graph/serialization.py

Serialization and benchmarking utilities for the NetworkX Code Intelligence graph.
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Tuple

import networkx as nx

_logger = logging.getLogger(__name__)


def save_graph_to_json(G: nx.DiGraph, filepath: Path):
    """Serialize NetworkX graph to JSON file using node_link_data per DT-4."""
    data = nx.node_link_data(G)
    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _logger.info("Saved Knowledge Graph to %s (%d nodes, %d edges)", filepath, G.number_of_nodes(), G.number_of_edges())


def load_graph_from_json(filepath: Path) -> nx.DiGraph:
    """Deserialize NetworkX graph from JSON file using node_link_graph per DT-4."""
    content = filepath.read_text(encoding="utf-8")
    data = json.loads(content)
    G = nx.node_link_graph(data)
    return G


def _find_path_of_length(G: nx.DiGraph, start_node: str, max_hops: int) -> List[str]:
    if start_node not in G:
        return []
    paths = nx.single_source_shortest_path(G, start_node, cutoff=max_hops)
    return next((path for path in paths.values() if len(path) == max_hops + 1), [])


def benchmark_graph_traversal(
    G: nx.DiGraph, start_node: str, max_hops: int = 5, repeats: int = 5
) -> Tuple[float, List[str]]:
    """Return (best elapsed_ms over `repeats` runs, sample_path); the minimum filters out scheduler noise."""
    best_ms = float("inf")
    path: List[str] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        path = _find_path_of_length(G, start_node, max_hops)
        best_ms = min(best_ms, (time.perf_counter() - t0) * 1000.0)
    return best_ms, path


__all__ = [
    "save_graph_to_json",
    "load_graph_from_json",
    "benchmark_graph_traversal",
]
