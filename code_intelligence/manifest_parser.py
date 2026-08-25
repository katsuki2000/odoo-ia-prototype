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

class MissingManifestError(Exception):
    """
    Raised by rag/graph.py::_load_module() when a module directory has no
    __manifest__.py and is not a known core module (see
    KNOWN_CORE_MODULE_DEPENDS below).

    This replaces the previous silent behavior (manifest=None, treated as
    "no dependencies" by topological_sort_modules with zero warning or
    exception). A missing manifest on a real module (miro_ai, custom_*, or
    any other addon) is a corpus bug that must fail loudly -- guessing its
    dependencies away is exactly what caused the account.move._reverse_moves
    override-order bug this exception guards against.
    """

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
        "is a defensive fallback and should not normally fire against the "
        "real Odoo addons corpus, which ships a real __manifest__.py for "
        "this module -- if this warning fires unexpectedly, check that "
        "addons_root actually points at a real, complete Odoo installation.",
        module_name, module_dir, KNOWN_CORE_MODULE_DEPENDS[module_name],
    )
    return OdooManifest(
        module_name=module_name,
        filepath="",
        name=module_name,
        depends=list(KNOWN_CORE_MODULE_DEPENDS[module_name]),
        synthesized=True,
    )
