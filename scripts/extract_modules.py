#!/usr/bin/env python3
"""
scripts/extract_modules.py

Generic, production-ready Code Intelligence extraction pipeline runner.
Can run on ANY Odoo project / custom addons directory.

Usage:
  python scripts/extract_modules.py /path/to/addons
  python scripts/extract_modules.py /path/to/addons --prefix custom_
  python scripts/extract_modules.py /path/to/addons --modules mod1 mod2
  python scripts/extract_modules.py /path/to/addons --output /path/to/output_dir
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from collections import Counter

# Add project root to PYTHONPATH
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import networkx as nx
from code_intelligence.extractor.manifest_parser import parse_manifest
from code_intelligence.extractor.python_extractor import extract_odoo_models_from_file
from code_intelligence.extractor.xml_extractor import (
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_server_actions_from_xml,
    parse_base_automations_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)
from code_intelligence.extractor.csv_extractor import parse_access_control_csv
from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.utils import discover_odoo_modules, compute_addons_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_modules")


def run_pipeline(addons_path: Path, module_names: list, output_dir: Path):
    """Run extraction pipeline over specified module list."""
    print("=" * 80)
    print(" CODE INTELLIGENCE — GENERALIZED EXTRACTION PIPELINE")
    print(f" Target Addons Path : {addons_path}")
    print(f" Discovered Modules : {len(module_names)} ({', '.join(module_names)})")
    print(f" Hash Digest        : {compute_addons_hash(addons_path, module_names)}")
    print("=" * 80)

    modules_dict = {}

    for mod_name in module_names:
        mod_dir = addons_path / mod_name
        if not mod_dir.exists():
            logger.warning(f"Module directory not found: {mod_dir}")
            continue

        manifest_path = mod_dir / "__manifest__.py"
        manifest = parse_manifest(manifest_path) if manifest_path.exists() else None
        mod = ParsedModule(manifest=manifest)

        # Parse Python files
        for py_f in mod_dir.rglob("*.py"):
            if py_f.name == "__manifest__.py":
                continue
            models = extract_odoo_models_from_file(py_f)
            mod.models.extend(models)

        # Parse XML files
        for xml_f in mod_dir.rglob("*.xml"):
            mod.rules.extend(parse_ir_rules_from_xml(xml_f))
            mod.groups.extend(parse_groups_from_xml(xml_f))
            mod.actions.extend(parse_actions_from_xml(xml_f))
            mod.server_actions.extend(parse_server_actions_from_xml(xml_f))
            mod.base_automations.extend(parse_base_automations_from_xml(xml_f))
            mod.menuitems.extend(parse_menuitems_from_xml(xml_f))
            mod.views.extend(parse_views_from_xml(xml_f))

        # Parse CSV files
        for csv_f in mod_dir.rglob("*.csv"):
            mod.acl_entries.extend(parse_access_control_csv(csv_f))

        modules_dict[mod_name] = mod
        print(f" Loaded module [{mod_name}]: {len(mod.models)} models, {len(mod.rules)} rules, {len(mod.groups)} groups, {len(mod.server_actions)} server actions, {len(mod.base_automations)} automations, {len(mod.acl_entries)} ACLs")

    print("\n--- Running Pass 1 & Pass 2 Symbol Resolution ---")
    registry = build_module_symbol_registry(modules_dict)

    print("\n--- Building NetworkX Knowledge Graph ---")
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    print("\n" + "=" * 80)
    print(" EXTRACTION RESULTS SUMMARY")
    print("=" * 80)
    print(f" Total Nodes: {G.number_of_nodes()}")
    print(f" Total Edges: {G.number_of_edges()}")

    node_counts = Counter(nx.get_node_attributes(G, "node_type").values())
    edge_counts = Counter(nx.get_edge_attributes(G, "edge_type").values())

    print("\n Node Types Distribution:")
    for k, v in sorted(node_counts.items()):
        print(f"   - {k:15s}: {v}")

    print("\n Edge Types Distribution:")
    for k, v in sorted(edge_counts.items()):
        print(f"   - {k:15s}: {v}")

    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "knowledge_graph.json"
    graph_data = nx.node_link_data(G)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)
    print(f"\n JSON Graph exported to: {json_path}")

    # GraphML Export
    G_clean = G.copy()
    for n, attrs in G_clean.nodes(data=True):
        for k, v in list(attrs.items()):
            if v is None:
                attrs[k] = ""
            elif isinstance(v, (list, dict)):
                attrs[k] = json.dumps(v)
    for u, v, attrs in G_clean.edges(data=True):
        for k, val in list(attrs.items()):
            if val is None:
                attrs[k] = ""
            elif isinstance(val, (list, dict)):
                attrs[k] = json.dumps(val)

    graphml_path = output_dir / "knowledge_graph.graphml"
    nx.write_graphml_xml(G_clean, graphml_path)
    print(f" GraphML exported to: {graphml_path}")
    print("=" * 80)

    return G, registry


def main():
    parser = argparse.ArgumentParser(description="Generic Odoo Code Intelligence Extraction Pipeline")
    parser.add_argument("addons_path", type=Path, help="Path to Odoo addons directory")
    parser.add_argument("--prefix", type=str, default=None, help="Filter modules by prefix (e.g. 'custom_')")
    parser.add_argument("--modules", nargs="+", default=None, help="Explicit list of module names to extract")
    parser.add_argument("--output", type=Path, default=None, help="Output directory for generated graphs")

    args = parser.parse_args()

    addons_path = args.addons_path.resolve()
    if not addons_path.exists():
        print(f"[ERROR] Addons directory does not exist: {addons_path}")
        sys.exit(1)

    if args.modules:
        module_names = args.modules
    else:
        module_names = discover_odoo_modules(addons_path, prefix=args.prefix)

    if not module_names:
        print(f"[ERROR] No Odoo modules found in {addons_path} matching criteria.")
        sys.exit(1)

    output_dir = args.output if args.output else addons_path / "knowledge_graph"
    run_pipeline(addons_path, module_names, output_dir)


if __name__ == "__main__":
    main()
