#!/usr/bin/env python3
"""
scripts/run_adversarial_extraction.py

Extraction pipeline runner for  (Agile ):
Runs the full Code Intelligence extraction pipeline over the 9 adversarial test modules
installed in odoo17-dev/addons.

Outputs:
 - Full summary statistics (Nodes, Edges, Node Types, Edge Types)
 - Unresolved reference categorization
 - Inheritance cycle detection
 - GraphML & JSON Graph exports
"""

import sys
import json
import logging
from pathlib import Path

# Add miro-rag to PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "miro-rag"))

import networkx as nx
from code_intelligence.knowledge_rules.extractor.manifest_parser import parse_manifest
from code_intelligence.knowledge_rules.extractor.python_extractor import extract_odoo_models_from_file
from code_intelligence.knowledge_rules.extractor.xml_extractor import (
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_server_actions_from_xml,
    parse_base_automations_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)
from code_intelligence.knowledge_rules.extractor.csv_extractor import parse_access_control_csv
from code_intelligence.knowledge_rules.graph import ParsedModule, build_module_symbol_registry
from code_intelligence.knowledge_rules.graph import OdooGraphBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("adversarial_extraction")

ADVERSARIAL_MODULE_NAMES = [
    "custom_credit_note_approval",
    "custom_credit_note_approval_regional",
    "custom_credit_note_approval_vip",
    "custom_hr_leave_workflow",
    "custom_purchase_request",
    "custom_asset_loan",
    "custom_automation_traps",
    "custom_credit_note_visibility_rules",
    "custom_expense_reimbursement_indirect",
]


def run_extraction():
    from config.settings import CUSTOM_ADDONS_PATH, CORE_ADDONS_PATH
    custom_root = Path(CUSTOM_ADDONS_PATH)
    core_root = Path(CORE_ADDONS_PATH)

    print("=" * 80)
    print(" CODE INTELLIGENCE - EXTRACTION PIPELINE ( / S2.3)")
    print(" Target: 9 Adversarial Test Modules")
    print("=" * 80)

    modules_dict = {}

    for mod_name in ADVERSARIAL_MODULE_NAMES:
        mod_dir = custom_root / mod_name
        if not mod_dir.exists():
            mod_dir = core_root / mod_name
        if not mod_dir.exists():
            print(f"[WARNING] Module directory not found: {mod_dir}")
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

    from collections import Counter
    node_counts = Counter(nx.get_node_attributes(G, "node_type").values())
    edge_counts = Counter(nx.get_edge_attributes(G, "edge_type").values())

    print("\n Node Types Distribution:")
    for k, v in sorted(node_counts.items()):
        print(f"   - {k:15s}: {v}")

    print("\n Edge Types Distribution:")
    for k, v in sorted(edge_counts.items()):
        print(f"   - {k:15s}: {v}")

    print("\n Unresolved Symbol References:")
    if registry.unresolved_references:
        for ref in registry.unresolved_references[:10]:
            print(f"   - [{ref.category.value}] Mod: {ref.source_module} Ref: {ref.symbol_ref} ({ref.ref_type})")
        if len(registry.unresolved_references) > 10:
            print(f"   ... ({len(registry.unresolved_references) - 10} more)")
    else:
        print("   None (All references resolved cleanly!)")

    print("\n Detected Inheritance Cycles:")
    if registry.detected_cycles:
        for cycle in registry.detected_cycles:
            print(f"   - {' -> '.join(cycle)}")
    else:
        print("   None detected.")

    # Export graph
    output_dir = addons_dir / "adversarial_test_modules"
    output_dir.mkdir(exist_ok=True)

    json_path = output_dir / "adversarial_graph.json"
    graph_data = nx.node_link_data(G)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)
    print(f"\n JSON Graph exported to: {json_path}")

    # Prepare sanitized graph for GraphML export (convert list/dict/None attributes to supported types)
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

    graphml_path = output_dir / "adversarial_graph.graphml"
    nx.write_graphml_xml(G_clean, graphml_path)
    print(f" GraphML exported to: {graphml_path}")
    print("=" * 80)

    return G, registry


if __name__ == "__main__":
    run_extraction()
