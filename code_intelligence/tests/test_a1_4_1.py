"""
code_intelligence/tests/test_a1_4_1.py

Full A1 end-to-end integration test: Python, XML, CSV and manifest extractors on the miro_ai module.
"""

from pathlib import Path

from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.extractor.xml import (
    parse_ir_rules_from_xml,
    parse_groups_from_xml,
    parse_actions_from_xml,
    parse_menuitems_from_xml,
    parse_views_from_xml,
)
from code_intelligence.extractor.csv import parse_access_control_csv
from code_intelligence.extractor.manifest import parse_manifest
from code_intelligence.tests._corpus_paths import CUSTOM_ADDONS_PATH


def test_end_to_end_a1_module_extraction():
    """Test Task A1.4.2: End-to-end integration test across the A1 extractors (Python, XML, CSV, Manifest)."""
    mod_dir = CUSTOM_ADDONS_PATH / "miro_ai"

    if mod_dir.exists():
        manifest_path = mod_dir / "__manifest__.py"
        manifest = parse_manifest(manifest_path)
        assert manifest is not None
        assert manifest.module_name == "miro_ai"

        # Python extraction
        py_models = []
        for py_file in mod_dir.rglob("*.py"):
            py_models.extend(extract_odoo_models_from_file(py_file))
        assert len(py_models) > 0

        # XML extraction
        xml_rules = []
        xml_groups = []
        xml_actions = []
        xml_menus = []
        xml_views = []
        for xml_file in mod_dir.rglob("*.xml"):
            xml_rules.extend(parse_ir_rules_from_xml(xml_file))
            xml_groups.extend(parse_groups_from_xml(xml_file))
            xml_actions.extend(parse_actions_from_xml(xml_file))
            xml_menus.extend(parse_menuitems_from_xml(xml_file))
            xml_views.extend(parse_views_from_xml(xml_file))

        assert len(xml_rules) > 0
        assert len(xml_groups) > 0

        # CSV extraction
        csv_acl = []
        for csv_file in mod_dir.rglob("*.csv"):
            csv_acl.extend(parse_access_control_csv(csv_file))
        assert len(csv_acl) > 0

        print(f"\n--- End-to-End A1 Module Summary ({mod_dir.name}) ---")
        print(f"Manifest:           {manifest.name} (depends: {manifest.depends})")
        print(f"Python Models:      {len(py_models)}")
        print(f"XML Rules:          {len(xml_rules)}")
        print(f"XML Groups:         {len(xml_groups)}")
        print(f"CSV ACL Entries:    {len(csv_acl)}")
