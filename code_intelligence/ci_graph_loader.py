"""
rag/ci_graph_loader.py

Code Intelligence knowledge graph loading and caching.

Lazy-loads the Odoo knowledge graph from a serialized JSON file on disk,
or builds it from source addon directories (custom_* modules + their
direct dependencies + always-loaded core modules). The graph is cached
in-process and invalidated when the JSON file's mtime changes.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


_CACHED_CODE_INTEL_GRAPH = None
_CACHED_GRAPH_MTIME = 0.0
GRAPH_JSON_PATH = Path(__file__).resolve().parent.parent / "code_intelligence" / "active_graph.json"


def _load_module(mod_dir: Path) -> tuple:
    """Load a single Odoo module directory into a ParsedModule.

    2026-08-06 fix (account.move._reverse_moves override-order bug): a
    missing __manifest__.py must NEVER silently become manifest=None here.
    cross_file_resolver.topological_sort_modules() only follows a module's
    real dependencies when `mod.manifest` is truthy -- manifest=None made it
    treat the module as a dependency-free leaf with no warning at all,
    corrupting load_order (and everything built from it: graph_builder's
    per-method override_sites, and method_override_resolver's reversal of
    that order into Odoo's real MRO execution order) whenever a module with
    real dependencies had no manifest on disk. See
    code_intelligence/manifest_parser.py::KNOWN_CORE_MODULE_DEPENDS /
    MissingManifestError for the full writeup and
    code_intelligence/tests/test_mixed_corpus_load_order.py for the
    regression test.

    2026-08-12 fix: the synthetic fake_data/code/ stand-in corpus (hand-
    maintained partial copies of a few Odoo core modules, used to give the
    graph something realistic to build a load order over before the real
    Odoo 17 corpus was wired in as addons_root) has been removed entirely.
    get_code_intelligence_graph() now loads 'account'/'sale'/'stock'
    directly from the real corpus, which ships a real __manifest__.py for
    every module -- so the synthesize-a-fallback-manifest path below is no
    longer expected to fire for those three in practice. The mechanism
    itself is kept as a defensive fallback (any future manifest-less
    directory, or a corpus without addons_root available) rather than
    removed, since it costs nothing to keep and MissingManifestError's
    fail-loudly behavior is still the right default for a genuinely
    unexpected manifest-less module.

    Resolution order when __manifest__.py is absent:
      1. A KNOWN_CORE_MODULE_DEPENDS entry (account/sale/stock) -> synthesize
         a manifest with its real, well-known, hardcoded `depends`. Kept as
         a defensive fallback; not expected to trigger against the real
         addons_root corpus, which always ships a real manifest for these.
      2. Directory with no .py files at all (e.g. a loose XML asset folder,
         not a real Odoo module) -> it can never declare a Model/Method, so
         it can never appear in a method override_sites list and its
         position in load_order cannot corrupt override-chain resolution.
         Safe to treat as a dependency-free leaf.
      3. Anything else (a real addon -- miro_ai, custom_*, or any other
         module actually containing code) -> raise MissingManifestError
         instead of guessing. A silently-guessed dependency set for a
         module we don't actually know is exactly the bug this fix removes.
    """
    from code_intelligence.manifest_parser import (
        parse_manifest,
        synthesize_fallback_manifest,
        MissingManifestError,
        KNOWN_CORE_MODULE_DEPENDS,
    )
    from code_intelligence.python_extractor import extract_odoo_models_from_file
    from code_intelligence.xml_extractor import (
        parse_ir_rules_from_xml, parse_groups_from_xml,
        parse_actions_from_xml, parse_menuitems_from_xml, parse_views_from_xml,
        parse_server_actions_from_xml, parse_base_automations_from_xml,
    )
    from code_intelligence.csv_extractor import parse_access_control_csv
    from code_intelligence.cross_file_resolver import ParsedModule

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
                    "(e.g. loose XML views), not a real Odoo module. It can "
                    "declare no Model/Method, so it cannot affect override-chain "
                    "resolution regardless of its position in load_order.",
                    module_name, mod_dir,
                )
                from code_intelligence.manifest_parser import OdooManifest
                manifest = OdooManifest(
                    module_name=module_name, filepath="", name=module_name,
                    depends=[], synthesized=True,
                )
            else:
                raise MissingManifestError(
                    f"Module '{module_name}' at {mod_dir} has no __manifest__.py, "
                    f"contains .py files, and is not a known core module "
                    f"({sorted(KNOWN_CORE_MODULE_DEPENDS)}). Refusing to "
                    f"silently treat it as having no dependencies -- this "
                    f"previously produced a wrong module load_order and a wrong "
                    f"method-override execution order with no error signal at "
                    f"all (see manifest_parser.MissingManifestError docstring). "
                    f"If this is a real Odoo module, add its __manifest__.py; if "
                    f"it's a new core module standing in for a real Odoo core "
                    f"addon, add it to KNOWN_CORE_MODULE_DEPENDS in "
                    f"code_intelligence/manifest_parser.py."
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


def get_code_intelligence_graph():
    """Lazy-load and cache Knowledge Graph for Code Intelligence node."""
    global _CACHED_CODE_INTEL_GRAPH, _CACHED_GRAPH_MTIME

    # Check if a built JSON graph exists and has been modified since last load
    try:
        if GRAPH_JSON_PATH.exists():
            current_mtime = GRAPH_JSON_PATH.stat().st_mtime
            if _CACHED_CODE_INTEL_GRAPH is None or current_mtime > _CACHED_GRAPH_MTIME:
                from code_intelligence.atomic_graph_swap import atomic_read_json
                from code_intelligence.graph_version import deserialize_graph_with_metadata
                
                logger.info("Loading graph from disk (mtime %s > %s)", current_mtime, _CACHED_GRAPH_MTIME)
                data_dict = atomic_read_json(GRAPH_JSON_PATH)
                G, metadata = deserialize_graph_with_metadata(data_dict)
                _CACHED_CODE_INTEL_GRAPH = G
                _CACHED_GRAPH_MTIME = current_mtime
                logger.info("Knowledge Graph loaded from JSON: %d nodes, %d edges (version: %s)", 
                            G.number_of_nodes(), G.number_of_edges(), metadata.get("git_commit", "unknown"))
                return _CACHED_CODE_INTEL_GRAPH
    except Exception as e:
        logger.error("Failed to load graph from %s: %s", GRAPH_JSON_PATH, e)
        # Fall back to building it

    if _CACHED_CODE_INTEL_GRAPH is not None:
        return _CACHED_CODE_INTEL_GRAPH

    logger.info("Building Knowledge Graph from source files...")
    from code_intelligence.utils import discover_odoo_modules
    from code_intelligence.cross_file_resolver import build_module_symbol_registry
    from code_intelligence.graph_builder import OdooGraphBuilder

    from config.settings import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH

    core_addons_root = Path(CORE_ADDONS_PATH)
    custom_addons_root = Path(CUSTOM_ADDONS_PATH)

    modules_dict = {}

    if not core_addons_root.exists():
        logger.warning(
            "CORE_ADDONS_PATH '%s' does not exist -- skipping core Odoo module "
            "preload (account/sale/stock). Set CORE_ADDONS_PATH in .env to "
            "point at a real Odoo addons/ directory.", core_addons_root,
        )
    if not custom_addons_root.exists():
        logger.warning(
            "CUSTOM_ADDONS_PATH '%s' does not exist -- skipping miro_ai and "
            "custom_* module discovery entirely (the graph will be built "
            "without any business module). Set CUSTOM_ADDONS_PATH in .env to "
            "point at this repo's odoo_addons/ directory.", custom_addons_root,
        )

    # Load core Odoo modules (account, sale, stock) directly from addons
    CORE_MODULES_ALWAYS_LOADED = ["account", "sale", "stock"]
    if core_addons_root.exists():
        for core_name in CORE_MODULES_ALWAYS_LOADED:
            core_dir = core_addons_root / core_name
            if core_dir.is_dir() and (core_dir / "__manifest__.py").exists():
                name, mod = _load_module(core_dir)
                modules_dict[name] = mod
            else:
                logger.warning(
                    "Core module '%s' not found (or has no __manifest__.py) under "
                    "%s -- skipping preload. Some override-chain regression "
                    "coverage may be reduced; this does not affect custom_* "
                    "modules, which are always loaded from CUSTOM_ADDONS_PATH below.",
                    core_name, core_addons_root,
                )

    miro_ai_dir = custom_addons_root / "miro_ai"
    if miro_ai_dir.exists():
        name, mod = _load_module(miro_ai_dir)
        modules_dict[name] = mod

    # Load adversarial custom_* modules for end-to-end benchmark support
    if custom_addons_root.exists():
        custom_modules = discover_odoo_modules(custom_addons_root, prefix="custom_")
        for mod_name in custom_modules:
            mod_dir = custom_addons_root / mod_name
            name, mod = _load_module(mod_dir)
            modules_dict[name] = mod

        # J36 fix (2026-08-07): custom_* modules routinely _inherit a REAL
        # Odoo core module (e.g. custom_expense_risk_base extends hr.expense
        # via depends=['hr_expense']) that is neither part of the always-
        # loaded core set above nor itself prefixed 'custom_', so it was
        # never loaded -- the extended model's base declaration (and its
        # real fields/methods) never entered the graph, and every tool call
        # against it returned "model not found" (confirmed root cause of the
        # J36 Sprint D replay failure, 0/8, eval_report_j36_expense_risk.md).
        # Load each custom_* module's DIRECT manifest dependencies too, one
        # level only -- not the full transitive closure. A real addon's
        # dependency chain quickly reaches base/mail/web and would balloon
        # load time for no benefit here: we only need the dependency's OWN
        # model declarations (e.g. hr.expense's _name + fields), not a
        # faithful simulation of everything base/mail/web themselves add.
        direct_deps = set()
        for mod_name in custom_modules:
            dep_mod = modules_dict.get(mod_name)
            if dep_mod and dep_mod.manifest:
                direct_deps.update(dep_mod.manifest.depends)

        for dep_name in sorted(direct_deps):
            if dep_name in modules_dict:
                continue  # already loaded (core preload, miro_ai, or another custom_* module)
            # A custom_* module's direct dependency is a core Odoo addon
            # (hr_expense, mail, product, ...), so it lives under
            # CORE_ADDONS_PATH, not alongside the custom_* sources.
            dep_dir = core_addons_root / dep_name
            if not dep_dir.is_dir() or not (dep_dir / "__manifest__.py").exists():
                # Not a real loadable addon here (e.g. 'base' ships as a
                # single file in this corpus, not a module directory) --
                # skip rather than guess; topological_sort_modules already
                # treats an unresolved dependency name as a harmless leaf.
                continue
            try:
                name, mod = _load_module(dep_dir)
                modules_dict[name] = mod
                logger.info(
                    "Loaded '%s' as a direct dependency of a custom_* module "
                    "(J36 fix) -- its base model declarations are now available "
                    "to models that _inherit it.", name,
                )
            except Exception as e:
                logger.error("Failed to load custom_* dependency '%s': %s", dep_name, e)

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    _CACHED_CODE_INTEL_GRAPH = builder.build_graph()
    
    # Save the freshly built graph so future requests or concurrent processes can load it fast
    try:
        from code_intelligence.atomic_graph_swap import atomic_write_json
        from code_intelligence.graph_version import serialize_graph_with_metadata
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
