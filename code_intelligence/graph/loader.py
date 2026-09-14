"""
code_intelligence/graph/build/disk_loader.py

Disk-level loading and validation helpers for Odoo addon modules and serialized graphs.
"""

import logging
from pathlib import Path
from typing import Tuple

from code_intelligence.extractor.csv import parse_access_control_csv
from code_intelligence.extractor.manifest import (
    KNOWN_CORE_MODULE_DEPENDS,
    MissingManifestError,
    OdooManifest,
    parse_manifest,
    synthesize_fallback_manifest,
)
from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.extractor.xml import (
    parse_actions_from_xml,
    parse_base_automations_from_xml,
    parse_groups_from_xml,
    parse_ir_rules_from_xml,
    parse_menuitems_from_xml,
    parse_server_actions_from_xml,
    parse_views_from_xml,
)
from .nodes import ParsedModule

logger = logging.getLogger(__name__)


def _load_module(mod_dir: Path) -> Tuple[str, ParsedModule]:
    """Parse an individual Odoo module directory into a ParsedModule instance."""
    manifest_p = mod_dir / "__manifest__.py"
    if manifest_p.exists():
        manifest = parse_manifest(manifest_p)
    else:
        module_name = mod_dir.name
        manifest = synthesize_fallback_manifest(module_name, mod_dir)
        if manifest is None:
            has_python_files = next(mod_dir.rglob("*.py"), None) is not None
            if not has_python_files:
                logger.info(
                    "Module directory '%s' at %s has no __manifest__.py and no "
                    ".py files -- treating as a non-module asset directory "
                    "(e.g. loose XML views), not a real Odoo module.",
                    module_name, mod_dir,
                )
                manifest = OdooManifest(
                    module_name=module_name, filepath="", name=module_name,
                    depends=[], synthesized=True,
                )
            else:
                raise MissingManifestError(
                    f"Module '{module_name}' at {mod_dir} has no __manifest__.py, "
                    f"contains .py files, and is not a known core module "
                    f"({sorted(KNOWN_CORE_MODULE_DEPENDS)}). Refusing to "
                    f"silently treat it as having no dependencies."
                )

    mod = ParsedModule(manifest=manifest)
    for py_f in mod_dir.rglob("*.py"):
        if py_f.name == "__manifest__.py":
            continue
        mod.models.extend(extract_odoo_models_from_file(py_f))
    for xml_f in mod_dir.rglob("*.xml"):
        mod.rules.extend(parse_ir_rules_from_xml(xml_f))
        mod.groups.extend(parse_groups_from_xml(xml_f))
        mod.actions.extend(parse_actions_from_xml(xml_f))
        mod.server_actions.extend(parse_server_actions_from_xml(xml_f))
        mod.base_automations.extend(parse_base_automations_from_xml(xml_f))
        mod.menuitems.extend(parse_menuitems_from_xml(xml_f))
        mod.views.extend(parse_views_from_xml(xml_f))
    for csv_f in mod_dir.rglob("*.csv"):
        mod.acl_entries.extend(parse_access_control_csv(csv_f))
    return mod_dir.name, mod


def _graph_filepaths_resolve_locally(G, sample_size: int = 20) -> bool:
    """
    Sanity-check that a graph loaded from disk actually points at real files on
    THIS machine, not at absolute paths baked in from another machine.
    """
    sampled = 0
    for _, attrs in G.nodes(data=True):
        if attrs.get("node_type") != "Model":
            continue
        for fp in attrs.get("filepaths", []):
            sampled += 1
            if Path(fp).exists():
                return True
            if sampled >= sample_size:
                return False
    return sampled == 0


__all__ = [
    "_load_module",
    "_graph_filepaths_resolve_locally",
]

# ── Graph Loader & Cache ─────────────────────────────────────────────────

"""
code_intelligence/graph/build/loader.py

Code Intelligence knowledge graph loading, caching, and building orchestration.
"""

import logging
import threading
from pathlib import Path

from .builder import OdooGraphBuilder
from .symbols import build_module_symbol_registry

logger = logging.getLogger(__name__)

_CACHED_CODE_INTEL_GRAPH = None
_CACHED_GRAPH_MTIME = 0.0
GRAPH_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "active_graph.json"

_GRAPH_BUILD_LOCK = threading.Lock()


def get_code_intelligence_graph():
    """Lazy-load and cache Knowledge Graph for Code Intelligence node."""
    global _CACHED_CODE_INTEL_GRAPH, _CACHED_GRAPH_MTIME

    # 1. Check if a built JSON graph exists on disk
    try:
        if GRAPH_JSON_PATH.exists():
            current_mtime = GRAPH_JSON_PATH.stat().st_mtime
            if _CACHED_CODE_INTEL_GRAPH is None or current_mtime > _CACHED_GRAPH_MTIME:
                from .atomic_swap import atomic_read_json
                from .version import deserialize_graph_with_metadata

                logger.info("Loading graph from disk (mtime %s > %s)", current_mtime, _CACHED_GRAPH_MTIME)
                data_dict = atomic_read_json(GRAPH_JSON_PATH)
                G, metadata = deserialize_graph_with_metadata(data_dict)

                if _graph_filepaths_resolve_locally(G):
                    _CACHED_CODE_INTEL_GRAPH = G
                    _CACHED_GRAPH_MTIME = current_mtime
                    logger.info(
                        "Knowledge Graph loaded from JSON: %d nodes, %d edges (version: %s)",
                        G.number_of_nodes(),
                        G.number_of_edges(),
                        metadata.get("git_commit", "unknown"),
                    )
                    return _CACHED_CODE_INTEL_GRAPH
                else:
                    logger.warning(
                        "Graph loaded from %s has Model filepaths that do not "
                        "exist on this machine -- discarding cache and rebuilding.",
                        GRAPH_JSON_PATH,
                    )
    except Exception as e:
        logger.error("Failed to load graph from %s: %s", GRAPH_JSON_PATH, e)

    if _CACHED_CODE_INTEL_GRAPH is not None:
        return _CACHED_CODE_INTEL_GRAPH

    logger.info("Building Knowledge Graph from source files...")
    from code_intelligence.utils import discover_odoo_modules
    from config.settings import (
        CORE_ADDONS_PATH,
        CORE_FRAMEWORK_ADDONS_PATH,
        CUSTOM_ADDONS_PATH,
        OCA_SAMPLE_ADDONS_PATH,
    )

    core_addons_root = Path(CORE_ADDONS_PATH)
    custom_addons_root = Path(CUSTOM_ADDONS_PATH)
    core_framework_addons_root = Path(CORE_FRAMEWORK_ADDONS_PATH)

    modules_dict = {}

    if not core_addons_root.exists():
        logger.warning(
            "CORE_ADDONS_PATH '%s' does not exist -- skipping core Odoo module preload.",
            core_addons_root,
        )
    if not custom_addons_root.exists():
        logger.warning(
            "CUSTOM_ADDONS_PATH '%s' does not exist -- skipping custom module discovery.",
            custom_addons_root,
        )

    # 2. Preload Core Modules
    CORE_MODULES_ALWAYS_LOADED = ["account", "sale", "stock", "purchase"]
    if core_addons_root.exists():
        for core_name in CORE_MODULES_ALWAYS_LOADED:
            core_dir = core_addons_root / core_name
            if core_dir.is_dir() and (core_dir / "__manifest__.py").exists():
                name, mod = _load_module(core_dir)
                modules_dict[name] = mod
            else:
                logger.warning(
                    "Core module '%s' not found (or has no __manifest__.py) under %s -- skipping preload.",
                    core_name, core_addons_root,
                )

    # 3. Load Custom Modules
    custom_modules = []
    if custom_addons_root.exists():
        custom_modules = discover_odoo_modules(custom_addons_root)
        for mod_name in custom_modules:
            mod_dir = custom_addons_root / mod_name
            name, mod = _load_module(mod_dir)
            modules_dict[name] = mod

    # 4. Load OCA Sample Modules (Bloc P3.1)
    OCA_SAMPLE_MODULE_REPOS = {
        "purchase_request": "purchase-workflow",
        "animal": "partner-contact-management",
        "base_tier_validation": "server-ux",
        "stock_inventory": "stock-logistics-warehouse",
        "sale_order_type": "sale-workflow",
        "account_invoice_section_sale_order": "account-invoicing",
        "database_cleanup": "server-tools",
        "stock_archive_constraint": "stock-logistics-warehouse",
        "auditlog": "server-tools",
        "kpi": "reporting-engine",
    }
    oca_modules_loaded = []
    if OCA_SAMPLE_ADDONS_PATH:
        oca_sample_root = Path(OCA_SAMPLE_ADDONS_PATH)
        if oca_sample_root.exists():
            for mod_name, repo_name in OCA_SAMPLE_MODULE_REPOS.items():
                mod_dir = oca_sample_root / repo_name / mod_name
                if not mod_dir.is_dir() or not (mod_dir / "__manifest__.py").exists():
                    logger.warning("OCA sample module '%s' not found under %s -- skipping.", mod_name, mod_dir)
                    continue
                try:
                    name, mod = _load_module(mod_dir)
                    modules_dict[name] = mod
                    oca_modules_loaded.append(name)
                except Exception as e:
                    logger.error("Failed to load OCA sample module '%s': %s", mod_name, e)
            logger.info(
                "Loaded %d/%d OCA sample modules from %s (Bloc P3.1).",
                len(oca_modules_loaded), len(OCA_SAMPLE_MODULE_REPOS), oca_sample_root,
            )

    # 5. Load Direct Dependencies
    direct_deps = set()
    for mod_name in custom_modules + oca_modules_loaded:
        dep_mod = modules_dict.get(mod_name)
        if dep_mod and dep_mod.manifest:
            direct_deps.update(dep_mod.manifest.depends)

    for dep_name in sorted(direct_deps):
        if dep_name in modules_dict:
            continue
        dep_dir = core_addons_root / dep_name
        if not dep_dir.is_dir() or not (dep_dir / "__manifest__.py").exists():
            fallback_dir = core_framework_addons_root / dep_name
            if fallback_dir.is_dir() and (fallback_dir / "__manifest__.py").exists():
                dep_dir = fallback_dir
            else:
                continue
        try:
            name, mod = _load_module(dep_dir)
            modules_dict[name] = mod
            logger.info("Loaded '%s' as a direct dependency.", name)
        except Exception as e:
            logger.error("Failed to load direct dependency '%s': %s", dep_name, e)

    # 6. Build and Cache Graph
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    _CACHED_CODE_INTEL_GRAPH = builder.build_graph()

    try:
        from .atomic_swap import atomic_write_json
        from .version import serialize_graph_with_metadata
        data_dict = serialize_graph_with_metadata(_CACHED_CODE_INTEL_GRAPH)
        atomic_write_json(data_dict, GRAPH_JSON_PATH)
        _CACHED_GRAPH_MTIME = GRAPH_JSON_PATH.stat().st_mtime
        logger.info("Saved freshly built graph to %s", GRAPH_JSON_PATH)
    except Exception as e:
        logger.error("Failed to save built graph to %s: %s", GRAPH_JSON_PATH, e)

    logger.info(
        "Knowledge Graph built: %d nodes, %d edges, %d modules",
        _CACHED_CODE_INTEL_GRAPH.number_of_nodes(),
        _CACHED_CODE_INTEL_GRAPH.number_of_edges(),
        len(modules_dict),
    )
    return _CACHED_CODE_INTEL_GRAPH


__all__ = [
    "get_code_intelligence_graph",
    "GRAPH_JSON_PATH",
    "_CACHED_CODE_INTEL_GRAPH",
    "_CACHED_GRAPH_MTIME",
]
