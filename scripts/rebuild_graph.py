#!/usr/bin/env python3
"""Force-rebuild active_graph.json from the real Odoo addons corpus.

The previous graph is kept aside while the new one is built. If the new graph could not use the
live Odoo inventory (authentication or connection failure, so only the static fallback modules
were loaded), the previous graph is put back and the script exits with an error, unless
--allow-offline is given.

Usage:
    python scripts/rebuild_graph.py [--allow-offline]
"""

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_intelligence.graph.loader import GRAPH_JSON_PATH, get_code_intelligence_graph


MIN_SOURCE_COVERAGE = 0.9


def runtime_backed(G) -> bool:
    """True when the graph was built from the live Odoo inventory, not the offline fallback."""
    fingerprint = G.graph.get("instance_fingerprint_data") or {}
    return bool(fingerprint.get("runtime_inventory_available"))


def source_coverage(G) -> float:
    """Share of the installed modules whose source code was found in the configured addon roots."""
    fingerprint = G.graph.get("instance_fingerprint_data") or {}
    installed = len(fingerprint.get("modules") or ())
    if not installed:
        return 1.0
    return len(fingerprint.get("source_modules") or ()) / installed


def missing_roots(G) -> list:
    fingerprint = G.graph.get("instance_fingerprint_data") or {}
    return [root for root, available in fingerprint.get("source_availability") or () if not available]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Force-rebuild active_graph.json.")
    parser.add_argument(
        "--allow-offline", action="store_true",
        help="Keep a graph built without the live Odoo inventory (static fallback modules).",
    )
    args = parser.parse_args(argv)

    previous = GRAPH_JSON_PATH.with_name(GRAPH_JSON_PATH.name + ".previous")
    if GRAPH_JSON_PATH.exists():
        size_mb = GRAPH_JSON_PATH.stat().st_size / (1024 * 1024)
        logger.info("Keeping the current graph aside: %s (%.1f MB)", previous, size_mb)
        shutil.copy2(GRAPH_JSON_PATH, previous)
    else:
        logger.info("No existing graph found at %s", GRAPH_JSON_PATH)

    logger.info("Rebuilding graph from source (this may take a minute)...")
    t0 = time.monotonic()
    G = get_code_intelligence_graph(force_rebuild=True)
    elapsed = time.monotonic() - t0

    if runtime_backed(G) and source_coverage(G) < MIN_SOURCE_COVERAGE and not args.allow_offline:
        if previous.exists():
            shutil.copy2(previous, GRAPH_JSON_PATH)
            logger.error("Previous graph restored from %s.", previous)
        logger.error(
            "The new graph holds the source of only %.0f%% of the installed modules (%d nodes); "
            "addon roots not found: %s. Check addons_path in odoo.conf. Use --allow-offline to keep it anyway.",
            source_coverage(G) * 100, G.number_of_nodes(), missing_roots(G) or "none",
        )
        return 2

    if not runtime_backed(G) and not args.allow_offline:
        if previous.exists():
            shutil.copy2(previous, GRAPH_JSON_PATH)
            logger.error("Previous graph restored from %s.", previous)
        logger.error(
            "The new graph was built without the live Odoo inventory (%d nodes, %d modules): "
            "check ODOO_ADMIN_PASSWORD and that Odoo is running. Use --allow-offline to keep it anyway.",
            G.number_of_nodes(), len(G.graph.get("instance_fingerprint_data", {}).get("modules", ())),
        )
        return 2

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
