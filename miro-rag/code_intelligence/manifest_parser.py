"""
code_intelligence/manifest_parser.py

Manifest parser for Odoo modules.
Implements Task A1.1.6: Parsing __manifest__.py (depends, data, unloaded files detection).
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Set
import logging

_logger = logging.getLogger(__name__)


@dataclass
class OdooManifest:
    module_name: str
    filepath: str
    name: str = ""
    version: str = ""
    summary: str = ""
    description: str = ""
    depends: List[str] = field(default_factory=list)
    data: List[str] = field(default_factory=list)
    demo: List[str] = field(default_factory=list)
    assets: Dict[str, List[str]] = field(default_factory=dict)
    installable: bool = True
    auto_install: bool = False
    unloaded_data_files: List[str] = field(default_factory=list)
    # 2026-08-06 fix (account.move._reverse_moves load-order bug): True when
    # this manifest was NOT parsed from a real __manifest__.py but built by
    # synthesize_fallback_manifest() below. Lets callers/tests tell a real
    # manifest apart from a hardcoded stand-in without re-deriving it from
    # filepath (which is legitimately empty for both a synthesized manifest
    # and some old test fixtures).
    synthesized: bool = False


def parse_manifest(manifest_path: Path) -> Optional[OdooManifest]:
    """
    Parse an Odoo __manifest__.py file safely and scan the module directory for unloaded data files.
    """
    if not manifest_path.exists() or manifest_path.name != "__manifest__.py":
        _logger.warning("Invalid manifest path: %s", manifest_path)
        return None

    module_dir = manifest_path.parent
    module_name = module_dir.name

    try:
        content = manifest_path.read_text(encoding="utf-8")
        manifest_dict = ast.literal_eval(content)
        if not isinstance(manifest_dict, dict):
            _logger.error("Manifest content is not a dictionary: %s", manifest_path)
            return None
    except Exception as e:
        _logger.error("Error parsing manifest %s: %s", manifest_path, e)
        return None

    raw_depends = manifest_dict.get("depends", [])
    depends = [str(d) for d in raw_depends] if isinstance(raw_depends, (list, tuple)) else []

    raw_data = manifest_dict.get("data", [])
    data = [str(d) for d in raw_data] if isinstance(raw_data, (list, tuple)) else []

    raw_demo = manifest_dict.get("demo", [])
    demo = [str(d) for d in raw_demo] if isinstance(raw_demo, (list, tuple)) else []

    raw_assets = manifest_dict.get("assets", {})
    assets = {}
    if isinstance(raw_assets, dict):
        for bundle, files in raw_assets.items():
            if isinstance(files, (list, tuple)):
                assets[str(bundle)] = [str(f) for f in files]

    # Detect XML and CSV files present in module dir but missing from 'data' and 'demo'
    loaded_files_set: Set[str] = set()
    for rel_path in data + demo:
        # Normalize relative paths
        clean_p = str(Path(rel_path))
        loaded_files_set.add(clean_p)

    unloaded_files: List[str] = []
    try:
        for ext in ("*.xml", "*.csv"):
            for data_file in module_dir.rglob(ext):
                rel = str(data_file.relative_to(module_dir))
                if rel not in loaded_files_set:
                    unloaded_files.append(rel)
    except Exception as e:
        _logger.error("Error scanning directory for unloaded files in %s: %s", module_dir, e)

    return OdooManifest(
        module_name=module_name,
        filepath=str(manifest_path),
        name=str(manifest_dict.get("name", "")),
        version=str(manifest_dict.get("version", "")),
        summary=str(manifest_dict.get("summary", "")),
        description=str(manifest_dict.get("description", "")),
        depends=depends,
        data=data,
        demo=demo,
        assets=assets,
        installable=bool(manifest_dict.get("installable", True)),
        auto_install=bool(manifest_dict.get("auto_install", False)),
        unloaded_data_files=sorted(unloaded_files),
    )


# ── 2026-08-06 fix: fake_data/code/ core-module manifest gap ─────────────────
#
# Root cause (found investigating a wrong method-override execution order on
# account.move._reverse_moves): fake_data/code/{account,sale,stock}/ simulate
# Odoo's own "core" addons to give the Code Intelligence corpus something
# realistic to extend/override, but they are NOT full Odoo modules and ship no
# __manifest__.py. rag/graph.py::_load_module() used to leave manifest=None
# in that case, and cross_file_resolver.topological_sort_modules()'s
# `if mod and mod.manifest:` guard then silently treated the module as having
# NO dependencies at all -- it never called mod.manifest.depends, it just
# appended the module to load_order wherever the outer `for name in
# modules_dict` loop happened to encounter it (i.e. filesystem iteration
# order, which is not guaranteed to be alphabetical and is not a dependency
# order). No exception, no warning: `if mod and mod.manifest` is `False` for
# `mod.manifest is None`, so the whole dependency-following branch is simply
# skipped.
#
# That corrupted load_order corrupts everything built from it downstream:
# graph_builder.py accumulates each Method node's override_sites in load_order
# sequence, and method_override_resolver.resoudre_chaine_surcharge_methode()
# reverses that sequence assuming it's a real dependency order (Odoo's MRO:
# the last-loaded/most-dependent module's override runs FIRST). Reversing an
# order that was never a real dependency order in the first place produces a
# wrong method-override execution order -- silently, with no error signal.
#
# Fix: never leave manifest=None for a module __load_module() is expected to
# load. For the handful of well-known fake_data/code/ core modules below,
# synthesize a manifest with hardcoded, stable, well-known Odoo dependencies
# (this is standard/public Odoo knowledge, not a guess). For anything else
# missing a manifest, _load_module() must raise MissingManifestError instead
# of guessing -- see rag/graph.py.


class MissingManifestError(Exception):
    """
    Raised by rag/graph.py::_load_module() when a module directory has no
    __manifest__.py and is not a known fake_data/code/ core module (see
    KNOWN_CORE_MODULE_DEPENDS below).

    This replaces the previous silent behavior (manifest=None, treated as
    "no dependencies" by topological_sort_modules with zero warning or
    exception). A missing manifest on a real module (miro_ai, custom_*, or
    any future fake_data/code/ addition) is a corpus bug that must fail
    loudly -- guessing its dependencies away is exactly what caused the
    account.move._reverse_moves override-order bug this exception guards
    against.
    """


# Scoped deliberately to the synthetic fake_data/code/ corpus only -- this is
# NOT a general-purpose Odoo dependency database and must never be consulted
# for real addons (miro_ai, custom_*, or a real odoo-17.0/addons tree). See
# rag/graph.py::_load_module(), which only falls back to this mapping when a
# module has no __manifest__.py at all; a real module with a real manifest
# always uses its own real `depends`, never this table.
#
# Dependencies below are the well-known, stable, public Odoo 17 `depends` for
# these core addons (not inferred from this corpus, not a guess) -- trimmed
# to the modules actually present or referenceable in fake_data/code/ plus
# their well-known real-world deps, since a dependency on a module absent
# from this corpus is harmless (topological_sort_modules already handles an
# unknown dependency name as a leaf with a warning).
KNOWN_CORE_MODULE_DEPENDS: Dict[str, List[str]] = {
    "account": ["base", "product", "mail", "portal", "analytic", "digest", "web"],
    "sale": ["account", "product", "stock", "mail", "portal", "utm", "digest"],
    "stock": ["base", "product", "mail", "portal", "barcodes", "web"],
}


def synthesize_fallback_manifest(module_name: str, module_dir: Path) -> Optional[OdooManifest]:
    """
    Build a minimal synthetic OdooManifest for a KNOWN_CORE_MODULE_DEPENDS
    entry that has no __manifest__.py on disk. Returns None if module_name
    isn't in the mapping -- callers must NOT fall back to manifest=None in
    that case (see MissingManifestError): only this explicit, reviewed list
    of core modules is allowed a guessed manifest.
    """
    if module_name not in KNOWN_CORE_MODULE_DEPENDS:
        return None
    _logger.warning(
        "Module '%s' at %s has no __manifest__.py -- synthesizing a fallback "
        "manifest with hardcoded depends=%s (KNOWN_CORE_MODULE_DEPENDS). This "
        "fallback is intended ONLY for the fake_data/code/ synthetic core "
        "corpus; if this warning fires for a real addon, add its real "
        "__manifest__.py instead of relying on this mapping.",
        module_name, module_dir, KNOWN_CORE_MODULE_DEPENDS[module_name],
    )
    return OdooManifest(
        module_name=module_name,
        filepath="",
        name=module_name,
        depends=list(KNOWN_CORE_MODULE_DEPENDS[module_name]),
        synthesized=True,
    )
