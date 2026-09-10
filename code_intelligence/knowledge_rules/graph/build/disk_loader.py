"""
code_intelligence/graph/build/disk_loader.py

Disk-level loading and validation helpers for Odoo addon modules and serialized graphs.
"""

import logging
from pathlib import Path
from typing import Tuple

from code_intelligence.knowledge_rules.extractor.csv_extractor import parse_access_control_csv
from code_intelligence.knowledge_rules.extractor.manifest_parser import (
    KNOWN_CORE_MODULE_DEPENDS,
    MissingManifestError,
    OdooManifest,
    parse_manifest,
    synthesize_fallback_manifest,
)
from code_intelligence.knowledge_rules.extractor.python_extractor import extract_odoo_models_from_file
from code_intelligence.knowledge_rules.extractor.xml_extractor import (
    parse_actions_from_xml,
    parse_base_automations_from_xml,
    parse_groups_from_xml,
    parse_ir_rules_from_xml,
    parse_menuitems_from_xml,
    parse_server_actions_from_xml,
    parse_views_from_xml,
)
from ..nodes.models import ParsedModule

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
