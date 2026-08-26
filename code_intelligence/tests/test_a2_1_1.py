"""
code_intelligence/tests/test_a2_1_1.py

Unit and Integration tests for Two-Pass Cross-File Reference Resolution.
Tests:
  1. Topological sort of modules based on manifest depends
  2. Two-pass symbol indexing and reference resolution
  3. Categorized unresolved references (absent_from_corpus, core_odoo_out_of_scope, probable_typo)
  4. Inheritance cycle detection (A2.1.4 with visited: set())
  5. Integration test A1+A2 on real corpus modules
"""

from pathlib import Path
import pytest

from code_intelligence.manifest_parser import OdooManifest, parse_manifest
from code_intelligence.python_extractor import (
    OdooModelDeclaration,
    extract_odoo_models_from_file,
)
from code_intelligence.xml_extractor import (
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)
from code_intelligence.csv_extractor import parse_access_control_csv
from code_intelligence.cross_file_resolver import (
    ParsedModule,
    UnresolvedCategory,
    topological_sort_modules,
    build_module_symbol_registry,
)


def test_topological_sort():
    """Test topological sorting of modules based on manifest depends."""
    mod_a = ParsedModule(manifest=OdooManifest(module_name="mod_a", filepath="", depends=[]))
    mod_b = ParsedModule(manifest=OdooManifest(module_name="mod_b", filepath="", depends=["mod_a"]))
    mod_c = ParsedModule(manifest=OdooManifest(module_name="mod_c", filepath="", depends=["mod_b"]))

    modules_dict = {"mod_c": mod_c, "mod_b": mod_b, "mod_a": mod_a}
    sorted_order = topological_sort_modules(modules_dict)

    # mod_a must come before mod_b, mod_b must come before mod_c
    assert sorted_order.index("mod_a") < sorted_order.index("mod_b")
    assert sorted_order.index("mod_b") < sorted_order.index("mod_c")


def test_unresolved_reference_categorization():
    """Test categorization of unresolved references (core_odoo_out_of_scope, absent, typo)."""
    mod_main = ParsedModule(
        manifest=OdooManifest(module_name="custom_sales", filepath="", depends=[]),
        models=[
            OdooModelDeclaration(
                class_name="CustomSale",
                filepath="custom_sales/models/sale.py",
                lineno=1,
                name="custom.sale",
                inherit=["sale.order", "nonexistent.module.model", "bad typo!!"],
            )
        ]
    )

    modules = {"custom_sales": mod_main}
    registry = build_module_symbol_registry(modules)

    unresolved = registry.unresolved_references
    assert len(unresolved) == 3

    categories = {u.symbol_ref: u.category for u in unresolved}

    # "sale.order" -> core_odoo_out_of_scope
    assert categories["sale.order"] == UnresolvedCategory.CORE_ODOO_OUT_OF_SCOPE

    # "nonexistent.module.model" -> absent_from_corpus
    assert categories["nonexistent.module.model"] == UnresolvedCategory.ABSENT_FROM_CORPUS

    # "bad typo!!" -> probable_typo
    assert categories["bad typo!!"] == UnresolvedCategory.PROBABLE_TYPO


def test_inheritance_cycle_detection():
    """Test Task A2.1.4: Inheritance cycle detection (visited: set())."""
    mod = ParsedModule(
        manifest=OdooManifest(module_name="cycle_mod", filepath="", depends=[]),
        models=[
            OdooModelDeclaration(
                class_name="ModelA",
                filepath="cycle_mod/a.py",
                lineno=1,
                name="model.a",
                inherit=["model.b"],
            ),
            OdooModelDeclaration(
                class_name="ModelB",
                filepath="cycle_mod/b.py",
                lineno=1,
                name="model.b",
                inherit=["model.a"],
            ),
        ]
    )

    modules = {"cycle_mod": mod}
    registry = build_module_symbol_registry(modules)

    assert len(registry.detected_cycles) > 0
    cycle = registry.detected_cycles[0]
    assert "model.a" in cycle
    assert "model.b" in cycle


def test_integration_a1_a2_real_corpus():
    """Test Task A2.1.5: Full A1+A2 two-pass resolution on real corpus modules."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    corpus_root = Path("/home/user/odoo-17.0/addons")

    modules_dict = {}

    # Load miro_ai module
    miro_ai_dir = Path("/home/user/odoo-17.0/addons") / "miro_ai"
    if miro_ai_dir.exists():
        manifest = parse_manifest(miro_ai_dir / "__manifest__.py")
        if manifest:
            mod = ParsedModule(manifest=manifest)
            for py_file in miro_ai_dir.rglob("*.py"):
                mod.models.extend(extract_odoo_models_from_file(py_file))
            for xml_file in miro_ai_dir.rglob("*.xml"):
                mod.rules.extend(parse_ir_rules_from_xml(xml_file))
                mod.groups.extend(parse_groups_from_xml(xml_file))
                mod.actions.extend(parse_actions_from_xml(xml_file))
                mod.menuitems.extend(parse_menuitems_from_xml(xml_file))
                mod.views.extend(parse_views_from_xml(xml_file))
            for csv_file in miro_ai_dir.rglob("*.csv"):
                mod.acl_entries.extend(parse_access_control_csv(csv_file))

            modules_dict["miro_ai"] = mod

    # Load sale module
    sale_dir = corpus_root / "sale"
    if sale_dir.exists():
        manifest_p = sale_dir / "__manifest__.py"
        manifest = parse_manifest(manifest_p) if manifest_p.exists() else OdooManifest(module_name="sale", filepath="", depends=["base"])
        mod = ParsedModule(manifest=manifest)
        for py_file in sale_dir.rglob("*.py"):
            mod.models.extend(extract_odoo_models_from_file(py_file))
        for xml_file in sale_dir.rglob("*.xml"):
            mod.views.extend(parse_views_from_xml(xml_file))

        modules_dict["sale"] = mod

    assert len(modules_dict) > 0

    registry = build_module_symbol_registry(modules_dict)

    print(f"\n--- A1+A2 Two-Pass Symbol Registry Summary ---")
    print(f"Indexed Models:          {len(registry.models)} (e.g. {list(registry.models.keys())[:5]})")
    print(f"Indexed XML Groups:      {len(registry.groups)}")
    print(f"Indexed Security Rules:  {len(registry.rules)}")
    print(f"Unresolved References:   {len(registry.unresolved_references)}")
    print(f"Detected Cycles:         {len(registry.detected_cycles)}")

    assert len(registry.models) > 0
    assert "sale.order" in registry.models or "miro.ai.settings" in registry.models
