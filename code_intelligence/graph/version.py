"""
code_intelligence/version.py

Graph Versioning & Metadata Manager:
Injects git commit hash, addons hash, schema version, node/edge counts, and generation timestamp
directly into graph JSON metadata.
"""

import datetime
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging
import networkx as nx

_logger = logging.getLogger(__name__)

GRAPH_SCHEMA_VERSION = 3


def get_git_commit_hash(repo_dir: Optional[Path] = None) -> str:
    """
    Retrieve current git commit hash. Falls back to 'unknown_commit' if git is unavailable.
    """
    if repo_dir is None:
        repo_dir = Path(__file__).resolve().parent.parent.parent

    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception as e:
        _logger.warning("Could not retrieve git commit hash: %s", e)

    return "unknown_commit"


def build_graph_metadata(
    G: nx.DiGraph,
    repo_dir: Optional[Path] = None,
    addons_hash: str = "",
    schema_version: int = GRAPH_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """
    Build structured metadata dictionary for the knowledge graph.
    """
    return {
        "git_commit": get_git_commit_hash(repo_dir),
        "addons_hash": addons_hash,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "graph_schema_version": schema_version,
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
    }


def serialize_graph_with_metadata(
    G: nx.DiGraph,
    repo_dir: Optional[Path] = None,
    addons_hash: str = "",
) -> Dict[str, Any]:
    """
    Serialize NetworkX DiGraph into a dictionary with metadata header.
    """
    from networkx.readwrite import json_graph

    data = json_graph.node_link_data(G)
    metadata = build_graph_metadata(G, repo_dir=repo_dir, addons_hash=addons_hash)

    return {
        "metadata": metadata,
        "graph": data,
    }


def deserialize_graph_with_metadata(data_dict: Dict[str, Any]) -> Tuple[nx.DiGraph, Dict[str, Any]]:
    """
    Deserialize dictionary back into (NetworkX DiGraph, metadata_dict).
    """
    from networkx.readwrite import json_graph

    metadata = data_dict.get("metadata", {})
    graph_data = data_dict.get("graph", data_dict)
    G = json_graph.node_link_graph(graph_data)

    return G, metadata
