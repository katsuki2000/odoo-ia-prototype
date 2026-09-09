"""
scripts/rebuild_graph.py

Force-rebuild active_graph.json from the real Odoo addons corpus.

Deletes the stale JSON first so get_code_intelligence_graph() falls
through to the build-from-source path, then saves the freshly built
graph with all current tags (Bloc P2) and metadata.

Usage:
    python scripts/rebuild_graph.py
"""

import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_intelligence.graph import GRAPH_JSON_PATH, get_code_intelligence_graph


def main():
    if GRAPH_JSON_PATH.exists():
        size_mb = GRAPH_JSON_PATH.stat().st_size / (1024 * 1024)
        logger.info("Removing stale graph: %s (%.1f MB)", GRAPH_JSON_PATH, size_mb)
        GRAPH_JSON_PATH.unlink()
    else:
        logger.info("No existing graph found at %s", GRAPH_JSON_PATH)

    logger.info("Rebuilding graph from source (this may take a minute)...")
    t0 = time.monotonic()
    G = get_code_intelligence_graph()
    elapsed = time.monotonic() - t0

    logger.info(
        "Done in %.1fs -- %d nodes, %d edges. Saved to %s (%.1f MB)",
        elapsed,
        G.number_of_nodes(),
        G.number_of_edges(),
        GRAPH_JSON_PATH,
        GRAPH_JSON_PATH.stat().st_size / (1024 * 1024) if GRAPH_JSON_PATH.exists() else 0,
    )

    # Quick sanity check: tags are present
    tagged = sum(1 for _, d in G.nodes(data=True) if d.get("behavioral_tags") or d.get("technical_tags"))
    logger.info("Nodes with at least one tag: %d / %d", tagged, G.number_of_nodes())
    if tagged == 0:
        logger.error("ZERO tagged nodes -- tags were not serialized. Check graph_builder.py.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
