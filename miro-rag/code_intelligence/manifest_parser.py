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
