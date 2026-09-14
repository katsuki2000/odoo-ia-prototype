from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH
"""
code_intelligence/tests/test_a1_4_1.py

Unit and Integration tests for JS client-side security checks & full A1 end-to-end integration.
Tests:
  1. JS user.hasGroup(...) pattern extraction with client_side_only=True
  2. OWL t-if="user.hasGroup(...)" pattern extraction with client_side_only=True
  3. Full A1 end-to-end integration test (Python + XML + CSV + JS extractors on full module)
"""

import tempfile
from pathlib import Path

from code_intelligence.extractor.js import parse_client_group_checks
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


def test_js_and_owl_hasgroup_extraction():
    """Test Task A1.4.1: JS user.hasGroup and OWL t-if user.hasGroup extraction with client_side_only=True."""
    js_code = """
import { Component } from "@odoo/owl";

export class SaleDashboard extends Component {
    setup() {
        this.isManager = this.env.user.hasGroup('sales_team.group_sale_manager');
    }
}
"""
    owl_code = """<templates xml:space="preserve">
    <t t-name="SaleDashboard">
        <div t-if="user.hasGroup('base.group_system')" class="admin-panel">
            <span>Admin Settings</span>
        </div>
    </t>
</templates>
"""

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f_js:
        f_js.write(js_code)
        f_js_path = Path(f_js.name)

    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f_owl:
        f_owl.write(owl_code)
        f_owl_path = Path(f_owl.name)

    try:
        # 1. Test JS check
        js_checks = parse_client_group_checks(f_js_path)
        assert len(js_checks) == 1
        check1 = js_checks[0]
        assert check1.group_id == "sales_team.group_sale_manager"
        assert check1.pattern_type == "js_hasGroup"
        assert check1.client_side_only is True

        # 2. Test OWL check
        owl_checks = parse_client_group_checks(f_owl_path)
        assert len(owl_checks) == 1
        check2 = owl_checks[0]
        assert check2.group_id == "base.group_system"
        assert check2.pattern_type == "owl_t_if_hasGroup"
        assert check2.client_side_only is True

    finally:
        f_js_path.unlink()
        f_owl_path.unlink()


def test_end_to_end_a1_module_extraction():
    """Test Task A1.4.2: End-to-end integration test across full A1 extractors (Python, XML, CSV, JS, Manifest)."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
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

        # JS extraction
        js_checks = []
        for js_file in mod_dir.rglob("*.js"):
            js_checks.extend(parse_client_group_checks(js_file))

        print(f"\n--- End-to-End A1 Module Summary ({mod_dir.name}) ---")
        print(f"Manifest:           {manifest.name} (depends: {manifest.depends})")
        print(f"Python Models:      {len(py_models)}")
        print(f"XML Rules:          {len(xml_rules)}")
        print(f"XML Groups:         {len(xml_groups)}")
        print(f"CSV ACL Entries:    {len(csv_acl)}")
        print(f"JS Group Checks:    {len(js_checks)}")
