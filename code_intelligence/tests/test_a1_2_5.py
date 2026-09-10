from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH
"""
code_intelligence/tests/test_a1_2_5.py

Integration tests for XML structural extraction on full real Odoo modules.
Runs XML extractors (ir.rule, res.groups, act_window, ir.model.fields, menuitems, ir.ui.view) across real XML files.
"""

from pathlib import Path
import pytest

from code_intelligence.knowledge_rules.extractor.xml_extractor import (
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_xml_fields_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)


def run_module_xml_extraction(module_path: Path):
    """
    Run all XML extractors across all .xml files in an Odoo module directory.
    Returns summary metrics.
    """
    xml_files = list(module_path.rglob("*.xml"))

    total_files = len(xml_files)
    parsed_files = 0
    
    rules = []
    groups = []
    actions = []
    xml_fields = []
    menuitems = []
    views = []
    total_buttons = 0

    for xml_file in xml_files:
        try:
            r = parse_ir_rules_from_xml(xml_file)
            g = parse_groups_from_xml(xml_file)
            a = parse_actions_from_xml(xml_file)
            f = parse_xml_fields_from_xml(xml_file)
            m = parse_menuitems_from_xml(xml_file)
            v = parse_views_from_xml(xml_file)

            rules.extend(r)
            groups.extend(g)
            actions.extend(a)
            xml_fields.extend(f)
            menuitems.extend(m)
            views.extend(v)

            for view_rec in v:
                total_buttons += len(view_rec.buttons)

            parsed_files += 1
        except Exception as e:
            print(f"Error parsing XML file {xml_file}: {e}")

    coverage_pct = (parsed_files / total_files * 100.0) if total_files > 0 else 0.0

    return {
        "module_name": module_path.name,
        "total_files": total_files,
        "parsed_files": parsed_files,
        "coverage_pct": coverage_pct,
        "rules_count": len(rules),
        "groups_count": len(groups),
        "actions_count": len(actions),
        "xml_fields_count": len(xml_fields),
        "menuitems_count": len(menuitems),
        "views_count": len(views),
        "buttons_count": total_buttons,
    }


def test_miro_ai_xml_integration():
    """Run XML integration test on odoo17-dev/addons/miro_ai."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    mod_dir = CUSTOM_ADDONS_PATH / "miro_ai"

    if mod_dir.exists():
        metrics = run_module_xml_extraction(mod_dir)

        print(f"\n--- XML Extraction Metrics for module: {metrics['module_name']} ---")
        print(f"Total XML Files:        {metrics['total_files']}")
        print(f"Parsed XML Files:       {metrics['parsed_files']}")
        print(f"Coverage Percentage:    {metrics['coverage_pct']:.1f}%")
        print(f"ir.rule Records:        {metrics['rules_count']}")
        print(f"res.groups Records:     {metrics['groups_count']}")
        print(f"Window Actions:         {metrics['actions_count']}")
        print(f"Menuitems Found:        {metrics['menuitems_count']}")
        print(f"Views Found:            {metrics['views_count']} (Buttons: {metrics['buttons_count']})")

        assert metrics["coverage_pct"] >= 90.0
        assert metrics["rules_count"] > 0
        assert metrics["groups_count"] > 0
        assert metrics["menuitems_count"] > 0


def test_sale_corpus_xml_integration():
    """Run XML integration test on addons/sale."""
    corpus_root = CORE_ADDONS_PATH
    sale_dir = corpus_root / "sale"

    if sale_dir.exists():
        metrics = run_module_xml_extraction(sale_dir)

        print(f"\n--- XML Extraction Metrics for module: {metrics['module_name']} ---")
        print(f"Total XML Files:        {metrics['total_files']}")
        print(f"Views Found:            {metrics['views_count']} (Buttons: {metrics['buttons_count']})")

        assert metrics["coverage_pct"] >= 90.0
        assert metrics["views_count"] > 0
        assert metrics["buttons_count"] > 0
