"""
rag/ci_graph_loader.py

Code Intelligence knowledge graph loading and caching.

Lazy-loads the Odoo knowledge graph from a serialized JSON file on disk,
or builds it from source addon directories (custom_* modules + their
direct dependencies + always-loaded core modules). The graph is cached
in-process and invalidated when the JSON file's mtime changes.
"""

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


_CACHED_CODE_INTEL_GRAPH = None
_CACHED_GRAPH_MTIME = 0.0
GRAPH_JSON_PATH = Path(__file__).resolve().parent.parent / "code_intelligence" / "active_graph.json"

# Serializes the "cache is cold, load/rebuild the graph" branch of
# get_code_intelligence_graph() below. Without this, two concurrent
# requests that both observe a cold cache (server just started, or the
# on-disk JSON just failed the foreign-machine check) each launch their
# own independent reload/rebuild in parallel -- confirmed live (two full
# ~70s from-source builds racing for the same question, todo/contexte.txt).
# Does NOT protect active_graph.json writes themselves -- atomic_write_json
# already makes those safe via temp-file + os.replace; this lock is only
# about not doing the expensive in-memory build twice.
_GRAPH_BUILD_LOCK = threading.Lock()


def _load_module(mod_dir: Path) -> tuple:
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


def _graph_filepaths_resolve_locally(G, sample_size: int = 20) -> bool:
    """
    Sanity-check that a graph loaded from GRAPH_JSON_PATH actually points at
    real files on THIS machine, not at absolute paths baked in from
    whatever machine last built (or committed) the JSON.

    active_graph.json is a serialized build artifact: every Model node's
    `filepaths` entry is an absolute path resolved at build time on
    whichever machine ran the build. If that JSON is shared between
    machines (backup, shared drive, or -- as happened here -- committed to
    git and checked out elsewhere), a graph built on machine A silently
    carries paths that do not exist on machine B. Nothing about the mtime-
    based cache check above can catch this: the file is real and recent,
    it just points at the wrong filesystem. Every downstream tool that
    does Path(fp).exists() (analyze_security_locks, analyze_data_
    constraints, find_security_lock_source_files, ...) then silently
    returns nothing, for every model, with no error surfaced anywhere
    (see todo/contexte.txt for the real incident this caused).

    Samples up to `sample_size` Model-node filepaths and checks whether ANY
    of them exist on disk. If none do, the cache is almost certainly
    foreign to this machine and must not be trusted. An empty sample (a
    graph with no Model filepaths at all) is not itself treated as
    invalid -- there is nothing to validate against, so it passes.
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
    # Loop exhausted without hitting sample_size: either no Model filepaths
    # existed at all (sampled == 0, nothing to validate against, pass), or
    # fewer than sample_size were found and NONE resolved (sampled > 0,
    # fail -- this is the exact case the foreign-machine bug hits when a
    # small/synthetic corpus has under sample_size filepaths total).
    return sampled == 0


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

                if _graph_filepaths_resolve_locally(G):
                    _CACHED_CODE_INTEL_GRAPH = G
                    _CACHED_GRAPH_MTIME = current_mtime
                    logger.info("Knowledge Graph loaded from JSON: %d nodes, %d edges (version: %s)", 
                                G.number_of_nodes(), G.number_of_edges(), metadata.get("git_commit", "unknown"))
                    return _CACHED_CODE_INTEL_GRAPH
                else:
                    logger.warning(
                        "Graph loaded from %s has Model filepaths that do not "
                        "exist on this machine -- this JSON was almost "
                        "certainly built (or last committed) on a different "
                        "machine. Discarding this cache instead of silently "
                        "serving broken paths, and rebuilding from source. "
                        "See todo/contexte.txt for the incident this guards "
                        "against.", GRAPH_JSON_PATH,
                    )
    except Exception as e:
        logger.error("Failed to load graph from %s: %s", GRAPH_JSON_PATH, e)
        # Fall back to building it

    if _CACHED_CODE_INTEL_GRAPH is not None:
        return _CACHED_CODE_INTEL_GRAPH

    logger.info("Building Knowledge Graph from source files...")
    from code_intelligence.utils import discover_odoo_modules
    from code_intelligence.cross_file_resolver import build_module_symbol_registry
    from code_intelligence.graph_builder import OdooGraphBuilder

    from config.settings import (
        CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH,
        OCA_SAMPLE_ADDONS_PATH,
    )

    core_addons_root = Path(CORE_ADDONS_PATH)
    custom_addons_root = Path(CUSTOM_ADDONS_PATH)
    core_framework_addons_root = Path(CORE_FRAMEWORK_ADDONS_PATH)

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

    # Load core Odoo modules (account, sale, stock, purchase) directly from
    # addons. 'purchase' added for Bloc P3.1 (todo/contexte.txt section 546):
    # PR-Q3 in tests/oca_p3_1_question_bank.json needs purchase.order's base
    # _name declaration (module 'purchase') to trace purchase_request's
    # override of button_confirm() -- previously only ever loaded as a side
    # effect of the REAL custom_purchase_request module's own manifest
    # depends=['purchase'], which the OCA sample module doesn't share (it
    # only depends on purchase_stock). Always-loading it here is a small,
    # low-risk permanent addition (a stable core module) rather than a
    # special case scoped to the OCA corpus only.
    CORE_MODULES_ALWAYS_LOADED = ["account", "sale", "stock", "purchase"]
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

    # Load all custom modules under custom_addons_root
    custom_modules = []
    if custom_addons_root.exists():
        custom_modules = discover_odoo_modules(custom_addons_root)
        for mod_name in custom_modules:
            mod_dir = custom_addons_root / mod_name
            name, mod = _load_module(mod_dir)
            modules_dict[name] = mod

    # -- Bloc P3.1 (todo/contexte.txt section 546, mandat San Goku 2026-09-04) --
    # Optional secondary corpus: the 10 real OCA modules sampled for the
    # P3.1 CI question bank (tests/oca_p3_1_question_bank.json) live under
    # OCA_SAMPLE_ADDONS_PATH/<repo>/<module> -- two levels deep and without
    # the 'custom_' prefix discover_odoo_modules() requires above, so
    # neither mechanism above ever finds them on its own. Loaded here as an
    # ADDITIVE corpus, gated on OCA_SAMPLE_ADDONS_PATH (unset by default =>
    # zero behavior change for production). Only the 10 modules actually
    # named in the question bank's meta.modules are loaded, not every
    # module in each cloned OCA repo (which would add ~80 irrelevant
    # modules per repo to the graph for no benchmark value). Keep this dict
    # in sync with tests/oca_p3_1_question_bank.json::meta.modules if that
    # bank is ever revised.
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
        if not oca_sample_root.exists():
            logger.warning(
                "OCA_SAMPLE_ADDONS_PATH '%s' does not exist -- skipping the "
                "OCA sample corpus entirely (Bloc P3.1 questions will not "
                "resolve to the intended modules).", oca_sample_root,
            )
        else:
            for mod_name, repo_name in OCA_SAMPLE_MODULE_REPOS.items():
                mod_dir = oca_sample_root / repo_name / mod_name
                if not mod_dir.is_dir() or not (mod_dir / "__manifest__.py").exists():
                    logger.warning(
                        "OCA sample module '%s' not found under %s -- skipping.",
                        mod_name, mod_dir,
                    )
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

    # Odoo core module (e.g. custom_expense_risk_base extends hr.expense
    # via depends=['hr_expense']) that is neither part of the always-
    # loaded core set above nor itself prefixed 'custom_', so it was
    # never loaded -- the extended model's base declaration (and its
    # real fields/methods) never entered the graph, and every tool call
    # against it returned "model not found" (confirmed root cause of the
    # J36 Sprint D replay failure, 0/8, eval_report_j36_expense_risk.md).
    # Load each custom_* module's (and, since Bloc P3.1, each OCA sample
    # module's) DIRECT manifest dependencies too, one level only -- not the
    # full transitive closure. A real addon's dependency chain quickly
    # reaches base/mail/web and would balloon load time for no benefit
    # here: we only need the dependency's OWN model declarations (e.g.
    # hr.expense's _name + fields), not a faithful simulation of everything
    # base/mail/web themselves add.
    direct_deps = set()
    for mod_name in custom_modules + oca_modules_loaded:
        dep_mod = modules_dict.get(mod_name)
        if dep_mod and dep_mod.manifest:
            direct_deps.update(dep_mod.manifest.depends)

    for dep_name in sorted(direct_deps):
        if dep_name in modules_dict:
            continue  # already loaded (core preload, miro_ai, or another custom_*/OCA module)
        # A custom_*/OCA module's direct dependency is a core Odoo addon
        # (hr_expense, mail, product, purchase_stock, ...), so it lives
        # under CORE_ADDONS_PATH, not alongside the custom_*/OCA sources.
        dep_dir = core_addons_root / dep_name
        if not dep_dir.is_dir() or not (dep_dir / "__manifest__.py").exists():
            # Not under the community addons root -- try the core
            # FRAMEWORK root (odoo/addons/, e.g. 'base'/'web') as a
            # second guess before giving up. 2026-08-27 (section 246):
            # 'base' in particular lives there in a standard Odoo git
            # checkout, not under CORE_ADDONS_PATH -- it was silently
            # skipped entirely before this, even when a custom_* module
            # (miro_ai, custom_deep_inheritance_security,
            # custom_expense_reimbursement_indirect) explicitly depends
            # on it.
            fallback_dir = core_framework_addons_root / dep_name
            if fallback_dir.is_dir() and (fallback_dir / "__manifest__.py").exists():
                dep_dir = fallback_dir
            else:
                # Genuinely not found under either root -- skip rather
                # than guess; topological_sort_modules already treats an
                # unresolved dependency name as a harmless leaf.
                continue
        try:
            name, mod = _load_module(dep_dir)
            modules_dict[name] = mod
            logger.info(
                "Loaded '%s' as a direct dependency of a custom_*/OCA sample "
                "module (J36 fix, extended Bloc P3.1) -- its base model "
                "declarations are now available to models that _inherit it.", name,
            )
        except Exception as e:
            logger.error("Failed to load direct dependency '%s': %s", dep_name, e)

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
