"""
code_intelligence/extractor/manifest_parser.py

Manifest parser for Odoo modules.
"""

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

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
    synthesized: bool = False


class MissingManifestError(Exception):
    """
    Raised when a module directory has no __manifest__.py and is not a known core module.
    """


KNOWN_CORE_MODULE_DEPENDS: Dict[str, List[str]] = {
    "account": ["base", "product", "mail", "portal", "analytic", "digest", "web"],
    "sale": ["account", "product", "stock", "mail", "portal", "utm", "digest"],
    "stock": ["base", "product", "mail", "portal", "barcodes", "web"],
}


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


def synthesize_fallback_manifest(module_name: str, module_dir: Path) -> Optional[OdooManifest]:
    """
    Build a minimal synthetic OdooManifest for a KNOWN_CORE_MODULE_DEPENDS
    entry that has no __manifest__.py on disk.
    """
    if module_name not in KNOWN_CORE_MODULE_DEPENDS:
        return None
    _logger.warning(
        "Module '%s' at %s has no __manifest__.py -- synthesizing a fallback "
        "manifest with hardcoded depends=%s (KNOWN_CORE_MODULE_DEPENDS).",
        module_name, module_dir, KNOWN_CORE_MODULE_DEPENDS[module_name],
    )
    return OdooManifest(
        module_name=module_name,
        filepath="",
        name=module_name,
        depends=list(KNOWN_CORE_MODULE_DEPENDS[module_name]),
        synthesized=True,
    )


__all__ = [
    "OdooManifest",
    "MissingManifestError",
    "KNOWN_CORE_MODULE_DEPENDS",
    "parse_manifest",
    "synthesize_fallback_manifest",
]

