"""
code_intelligence/graph/build/disk_loader.py

Disk-level loading and validation helpers for Odoo addon modules and serialized graphs.
"""

import logging
import threading
from pathlib import Path
from typing import Tuple

from config.settings import GRAPH_CACHE_PATH
from code_intelligence.extractor.csv import ACCESS_CONTROL_CSV_NAME, parse_access_control_csv
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
from .translations import load_module_translations
from .translations import attach_runtime_translations
from .runtime_translations import read_runtime_translations
from .nodes import ParsedModule

logger = logging.getLogger(__name__)


def _load_module(
    mod_dir: Path,
    translation_languages=None,
) -> Tuple[str, ParsedModule]:
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
    mod.translations = load_module_translations(mod_dir, mod_dir.name, translation_languages)
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
    for csv_f in mod_dir.rglob(ACCESS_CONTROL_CSV_NAME):
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

import configparser
import logging
import os
import threading
from pathlib import Path

from .builder import OdooGraphBuilder
from .symbols import build_module_symbol_registry

logger = logging.getLogger(__name__)

_CACHED_CODE_INTEL_GRAPH = None
_CACHED_GRAPH_MTIME = 0.0
_CACHED_TRANSLATION_LANGUAGES: tuple[str, ...] = ()
_GRAPH_LOAD_LOCK = threading.RLock()


def _translation_cache_matches(requested, available) -> bool:
    requested = set(requested)
    available = set(available)
    return requested.issubset(available)


def _normalize_language_code(language: str) -> str:
    return language.strip().replace("-", "_")
GRAPH_JSON_PATH = Path(GRAPH_CACHE_PATH)

_GRAPH_BUILD_LOCK = threading.Lock()

# Native core modules always considered for preload into the production
# graph -- Bloc N1 validation perimeter (todo/contexte.txt sections
# 747-748, 753): purchase, sale, account, stock, maintenance. Filtered
# against the target instance's real installed state by
# _discover_installed_core_modules() before use (section 752).
CORE_MODULE_CANDIDATES = ["account", "sale", "stock", "purchase", "maintenance"]


def _open_technical_session():
    """Open a technical connector and return it with its authenticated uid."""
    from erp_data.odoo_connector import OdooConnector

    connector = OdooConnector(technical=True)
    return connector, connector.authenticate(connector.username)


def _read_runtime_module_inventory():
    """Read the installed-module inventory, or return None when unavailable."""
    try:
        connector, uid = _open_technical_session()
        return connector.search_read(
            uid=uid,
            model="ir.module.module",
            domain=[("state", "=", "installed")],
            fields=["name", "installed_version", "latest_version", "state"],
        )
    except Exception as error:
        logger.warning("Could not read the live installed-module inventory: %s", error)
        return None


def _read_runtime_active_languages():
    """Read active language codes, or return None when runtime metadata is unavailable."""
    try:
        connector, uid = _open_technical_session()
        records = connector.search_read(
            uid=uid,
            model="res.lang",
            domain=[("active", "=", True)],
            fields=["code"],
        )
        return sorted({str(record["code"]) for record in records if record.get("code")})
    except Exception as error:
        logger.warning("Could not read active runtime languages: %s", error)
        return None


def _read_runtime_translations(requested_languages, active_languages):
    """Read registry labels for requested languages when the instance exposes them."""
    try:
        connector, uid = _open_technical_session()
        return read_runtime_translations(
            connector,
            uid,
            requested_languages,
            active_languages,
        )
    except Exception as error:
        logger.warning("Could not read live runtime translations: %s", error)
        return [], {
            "active_languages_available": active_languages is not None,
            "requested_languages": sorted(requested_languages),
            "queried_languages": [],
            "model_records": 0,
            "field_records": 0,
            "failed_languages": ["runtime_unavailable"],
        }


def _installed_module_names(installed_modules) -> set[str]:
    """Return valid installed module names from runtime inventory rows."""
    if installed_modules is None:
        return set()
    return {
        str(record["name"])
        for record in installed_modules
        if record.get("name")
    }


def _normalize_addon_roots(paths) -> list[Path]:
    roots = (
        Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()
        for path in paths
        if path
    )
    return list(dict.fromkeys(roots))


def _configured_addon_roots(
    config_path,
    fallback_roots,
    odoo_default_roots=None,
) -> list[Path]:
    """Resolve addon roots using Odoo's configured order or an explicit fallback."""
    config_file = Path(config_path).expanduser() if config_path else None
    if config_file and config_file.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        try:
            with config_file.open(encoding="utf-8") as stream:
                parser.read_file(stream)
            configured_paths = parser.get("options", "addons_path", fallback="").strip()
        except (OSError, configparser.Error) as error:
            logger.warning(
                "Could not read Odoo configuration '%s' (%s); using explicit addon-path fallback.",
                config_file,
                error,
            )
        else:
            if configured_paths:
                roots = _normalize_addon_roots(configured_paths.split(","))
                if roots:
                    logger.info(
                        "Using %d addon roots in the order declared by Odoo config '%s'.",
                        len(roots),
                        config_file,
                    )
                    return roots
            logger.info(
                "Odoo configuration '%s' does not set addons_path; using Odoo's default addon roots.",
                config_file,
            )
            return _normalize_addon_roots(
                odoo_default_roots if odoo_default_roots is not None else fallback_roots
            )
    else:
        logger.warning(
            "ODOO_CONF_PATH is unset or unavailable (%s); addon-root precedence cannot be "
            "confirmed against the live Odoo process. Using explicit fallback roots.",
            config_file,
        )

    return _normalize_addon_roots(fallback_roots)


def _discover_installed_source_modules(addon_roots, installed_modules) -> dict[str, Path]:
    """Map installed module names to source directories using Odoo addon-path order."""
    installed_names = _installed_module_names(installed_modules)
    modules = {}
    for root in addon_roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for module_name in sorted(installed_names):
            module_dir = root / module_name
            if not (module_dir / "__manifest__.py").is_file():
                continue
            if module_name in modules:
                logger.warning(
                    "Installed addon '%s' exists in multiple roots; keeping '%s' "
                    "according to configured addon-root priority and ignoring '%s'.",
                    module_name, modules[module_name], module_dir,
                )
                continue
            modules[module_name] = module_dir
    return modules


def _discover_installed_core_modules(candidates: list, installed_modules=None) -> list:
    """
    Resolve which of the candidate core module names are actually installed
    on the target Odoo instance, by querying ir.module.module (state=
    installed) through OdooConnector -- so the set of natively-preloaded
    modules reflects the real instance, not a fixed benchmark assumption.

    Falls back to the full candidate list, unfiltered, if the instance is
    unreachable at graph-build time (offline builds, OCA-only benchmark
    runs, no live Odoo instance configured) -- explicit fallback per
    todo/rules.md (machine-dependent values need a fallback, never a silent
    hard assumption). See todo/contexte.txt section 752.
    """
    if installed_modules is None:
        try:
            connector, uid = _open_technical_session()
            installed_modules = connector.search_read(
                uid=uid,
                model="ir.module.module",
                domain=[("state", "=", "installed"), ("name", "in", candidates)],
                fields=["name"],
            )
        except Exception as error:
            logger.warning(
                "Could not query ir.module.module on the live Odoo instance (%s) "
                "-- falling back to the static core module candidate list %s.",
                error, candidates,
            )
            return candidates

    try:
        installed = _installed_module_names(installed_modules)
    except (KeyError, TypeError) as error:
        logger.warning(
            "Could not query ir.module.module on the live Odoo instance (%s) "
            "-- falling back to the static core module candidate list %s.",
            error, candidates,
        )
        return candidates

    if not installed:
        logger.info(
            "No candidate core modules are installed on this instance; skipping: %s",
            candidates,
        )
        return []

    missing = [c for c in candidates if c not in installed]
    if missing:
        logger.info(
            "Core module candidates not installed on this instance, skipping: %s",
            missing,
        )
    return [c for c in candidates if c in installed]


def _get_code_intelligence_graph(
    *,
    translation_languages=None,
    installed_modules=None,
    active_languages=None,
    request_language=None,
    force_rebuild=False,
):
    """Lazy-load and cache Knowledge Graph for Code Intelligence node."""
    global _CACHED_CODE_INTEL_GRAPH, _CACHED_GRAPH_MTIME, _CACHED_TRANSLATION_LANGUAGES
    requested_languages = tuple(sorted({
        _normalize_language_code(language)
        for language in (translation_languages or ())
        if language and language.strip()
    }))
    request_language = _normalize_language_code(request_language) if request_language else None
    if request_language:
        requested_languages = tuple(sorted(set(requested_languages) | {request_language}))

    from config.settings import (
        CORE_ADDONS_PATH,
        CORE_FRAMEWORK_ADDONS_PATH,
        CUSTOM_ADDONS_PATH,
        OCA_SAMPLE_ADDONS_PATH,
        ODOO_CONF_PATH,
    )

    core_addons_root = Path(CORE_ADDONS_PATH)
    custom_addons_root = Path(CUSTOM_ADDONS_PATH)
    addon_roots = _configured_addon_roots(
        ODOO_CONF_PATH,
        [CORE_FRAMEWORK_ADDONS_PATH, CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH],
        [CORE_FRAMEWORK_ADDONS_PATH, CORE_ADDONS_PATH],
    )
    expected_addon_roots = [str(root) for root in addon_roots]

    if _CACHED_CODE_INTEL_GRAPH is not None and not force_rebuild:
        requested_languages = tuple(sorted(
            set(requested_languages)
            | set(_CACHED_CODE_INTEL_GRAPH.graph.get("translation_languages", ()))
        ))

    # 1. Check if a built JSON graph exists on disk
    try:
        if GRAPH_JSON_PATH.exists():
            current_mtime = GRAPH_JSON_PATH.stat().st_mtime
            cached_languages = set(
                _CACHED_CODE_INTEL_GRAPH.graph.get("translation_languages", ())
                if _CACHED_CODE_INTEL_GRAPH is not None else ()
            )
            if (
                force_rebuild
                or _CACHED_CODE_INTEL_GRAPH is None
                or current_mtime > _CACHED_GRAPH_MTIME
                or not _translation_cache_matches(requested_languages, cached_languages)
            ):
                from .atomic_swap import atomic_read_json
                from .version import GRAPH_SCHEMA_VERSION, deserialize_graph_with_metadata

                logger.info("Loading graph from disk (mtime %s > %s)", current_mtime, _CACHED_GRAPH_MTIME)
                data_dict = atomic_read_json(GRAPH_JSON_PATH)
                G, metadata = deserialize_graph_with_metadata(data_dict)

                graph_languages = set(G.graph.get("translation_languages", ()))
                schema_valid = metadata.get("graph_schema_version", 0) >= GRAPH_SCHEMA_VERSION
                paths_resolve = _graph_filepaths_resolve_locally(G)
                addon_roots_match = G.graph.get("addon_roots_ordered") == expected_addon_roots
                languages_match = _translation_cache_matches(requested_languages, graph_languages)
                if schema_valid and paths_resolve and not languages_match and not force_rebuild:
                    requested_languages = tuple(sorted(set(requested_languages) | graph_languages))
                    languages_match = _translation_cache_matches(requested_languages, graph_languages)
                if (
                    schema_valid
                    and paths_resolve
                    and addon_roots_match
                    and languages_match
                    and not force_rebuild
                ):
                    _CACHED_CODE_INTEL_GRAPH = G
                    _CACHED_GRAPH_MTIME = current_mtime
                    _CACHED_TRANSLATION_LANGUAGES = tuple(sorted(graph_languages))
                    logger.info(
                        "Knowledge Graph loaded from JSON: %d nodes, %d edges (version: %s)",
                        G.number_of_nodes(),
                        G.number_of_edges(),
                        metadata.get("git_commit", "unknown"),
                    )
                    return _CACHED_CODE_INTEL_GRAPH
                if not paths_resolve:
                    logger.warning(
                        "Graph loaded from %s has Model filepaths that do not "
                        "exist on this machine -- discarding cache and rebuilding.",
                        GRAPH_JSON_PATH,
                    )
                elif not addon_roots_match:
                    logger.info(
                        "Graph cache addon-root order differs from the current Odoo configuration; rebuilding."
                    )
                elif not languages_match:
                    logger.info(
                        "Graph cache does not contain requested translation languages %s; rebuilding.",
                        requested_languages,
                    )
                elif not schema_valid:
                    logger.info("Graph cache schema is stale; rebuilding.")
    except Exception as e:
        logger.error("Failed to load graph from %s: %s", GRAPH_JSON_PATH, e)

    if _CACHED_CODE_INTEL_GRAPH is not None and not force_rebuild:
        cached_languages = _CACHED_CODE_INTEL_GRAPH.graph.get("translation_languages", ())
        if _translation_cache_matches(requested_languages, cached_languages):
            return _CACHED_CODE_INTEL_GRAPH
        _CACHED_CODE_INTEL_GRAPH = None

    logger.info("Building Knowledge Graph from source files...")
    from code_intelligence.utils import discover_odoo_modules

    modules_dict = {}
    installed_source_modules = {}

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

    # 2. Load installed modules whose source is accessible. A runtime inventory
    # replaces the fixed core shortlist; unavailable runtime access retains the
    # narrow offline fallback below.
    if installed_modules is None:
        installed_modules = _read_runtime_module_inventory()
    if active_languages is None:
        active_languages = _read_runtime_active_languages()
    if installed_modules is not None:
        installed_source_modules = _discover_installed_source_modules(
            addon_roots,
            installed_modules,
        )
        for module_name, module_dir in installed_source_modules.items():
            try:
                name, mod = _load_module(module_dir, requested_languages)
                modules_dict[name] = mod
            except Exception as error:
                logger.error("Failed to load installed module '%s': %s", module_name, error)
        logger.info(
            "Loaded %d/%d installed modules from configured addon paths.",
            len(modules_dict), len(_installed_module_names(installed_modules)),
        )
    else:
        core_modules_always_loaded = _discover_installed_core_modules(CORE_MODULE_CANDIDATES)
        for core_name in core_modules_always_loaded:
            core_dir = next(
                (
                    root / core_name
                    for root in addon_roots
                    if (root / core_name / "__manifest__.py").is_file()
                ),
                None,
            )
            if core_dir is not None:
                name, mod = _load_module(core_dir, requested_languages)
                modules_dict[name] = mod

        if custom_addons_root.exists():
            for mod_name in discover_odoo_modules(custom_addons_root):
                name, mod = _load_module(custom_addons_root / mod_name, requested_languages)
                modules_dict[name] = mod

    custom_modules = (
        [
            name
            for name, module_dir in installed_source_modules.items()
            if module_dir.parent.resolve() == custom_addons_root.resolve()
        ]
        if installed_modules is not None
        else discover_odoo_modules(custom_addons_root)
    )

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
                if installed_modules is not None and mod_name not in _installed_module_names(installed_modules):
                    continue
                mod_dir = oca_sample_root / repo_name / mod_name
                if not mod_dir.is_dir() or not (mod_dir / "__manifest__.py").exists():
                    logger.warning("OCA sample module '%s' not found under %s -- skipping.", mod_name, mod_dir)
                    continue
                try:
                    name, mod = _load_module(mod_dir, requested_languages)
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

    installed_module_names = (
        _installed_module_names(installed_modules)
        if installed_modules is not None else None
    )
    for dep_name in sorted(direct_deps):
        if dep_name in modules_dict:
            continue
        if installed_module_names is not None and dep_name not in installed_module_names:
            logger.warning(
                "Skipping dependency '%s' absent from the runtime installed-module inventory.",
                dep_name,
            )
            continue
        dep_dir = next(
            (
                root / dep_name
                for root in addon_roots
                if (root / dep_name / "__manifest__.py").is_file()
            ),
            None,
        )
        if dep_dir is None:
            logger.warning(
                "Skipping dependency '%s': no manifest found in configured addon roots.",
                dep_name,
            )
            continue
        try:
            name, mod = _load_module(dep_dir, requested_languages)
            modules_dict[name] = mod
            logger.info("Loaded '%s' as a direct dependency.", name)
        except Exception as e:
            logger.error("Failed to load direct dependency '%s': %s", dep_name, e)

    # 6. Build and Cache Graph
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    _CACHED_CODE_INTEL_GRAPH = builder.build_graph()
    runtime_translation_records, runtime_translation_summary = _read_runtime_translations(
        requested_languages,
        active_languages,
    )
    runtime_attachment_summary = attach_runtime_translations(
        _CACHED_CODE_INTEL_GRAPH,
        runtime_translation_records,
    )
    _CACHED_CODE_INTEL_GRAPH.graph["runtime_translation_summary"] = {
        **runtime_translation_summary,
        **runtime_attachment_summary,
    }
    _CACHED_TRANSLATION_LANGUAGES = requested_languages
    from .instance_fingerprint import build_instance_fingerprint
    source_modules = {
        name: str(mod.manifest.version or "")
        for name, mod in modules_dict.items()
        if mod and mod.manifest
    }
    source_paths = addon_roots
    if OCA_SAMPLE_ADDONS_PATH:
        source_paths.append(Path(OCA_SAMPLE_ADDONS_PATH))
    fingerprint = build_instance_fingerprint(
        installed_modules=installed_modules,
        addon_paths=source_paths,
        active_languages=active_languages,
        request_language=request_language or (requested_languages[0] if len(requested_languages) == 1 else None),
        source_modules=source_modules,
    )
    _CACHED_CODE_INTEL_GRAPH.graph["addon_roots_ordered"] = expected_addon_roots
    _CACHED_CODE_INTEL_GRAPH.graph["instance_fingerprint"] = fingerprint.digest
    _CACHED_CODE_INTEL_GRAPH.graph["instance_fingerprint_data"] = fingerprint.to_dict()
    _CACHED_CODE_INTEL_GRAPH.graph["translation_languages"] = list(requested_languages)

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


def get_code_intelligence_graph(
    *,
    translation_languages=None,
    installed_modules=None,
    active_languages=None,
    request_language=None,
    force_rebuild=False,
):
    with _GRAPH_LOAD_LOCK:
        return _get_code_intelligence_graph(
            translation_languages=translation_languages,
            installed_modules=installed_modules,
            active_languages=active_languages,
            request_language=request_language,
            force_rebuild=force_rebuild,
        )


__all__ = [
    "get_code_intelligence_graph",
    "GRAPH_JSON_PATH",
    "_CACHED_CODE_INTEL_GRAPH",
    "_CACHED_GRAPH_MTIME",
    "_CACHED_TRANSLATION_LANGUAGES",
    "CORE_MODULE_CANDIDATES",
    "_discover_installed_core_modules",
]
