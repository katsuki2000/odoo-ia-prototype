from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH
"""
code_intelligence/tests/test_a1_1_6.py

Unit tests for Task A1.1.6: Manifest parser (__manifest__.py).
Tests:
  1. Manifest parsing: depends, data extraction
  2. Unloaded data file detection (XML/CSV file in folder but missing from 'data')
  3. Real manifest test on odoo17-dev/addons/miro_ai/__manifest__.py
"""

import tempfile
from pathlib import Path

from code_intelligence.knowledge_rules.extractor.manifest_parser import parse_manifest


def test_manifest_parsing_and_unloaded_detection():
    """Test manifest parsing and detection of XML files missing from data."""
    manifest_content = """
{
    'name': 'Test Module',
    'version': '1.0',
    'depends': ['base', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/test_views.xml',
    ],
    'installable': True,
}
"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mod_dir = Path(tmp_dir) / "custom_module"
        mod_dir.mkdir()
        
        manifest_path = mod_dir / "__manifest__.py"
        manifest_path.write_text(manifest_content, encoding="utf-8")

        # Create dummy loaded files
        (mod_dir / "security").mkdir()
        (mod_dir / "security" / "ir.model.access.csv").write_text("dummy csv")

        (mod_dir / "views").mkdir()
        (mod_dir / "views" / "test_views.xml").write_text("<xml/>")

        # Create an UNLOADED xml file (present in folder, but NOT in data)
        (mod_dir / "views" / "orphan_view.xml").write_text("<xml/>")

        # Parse manifest
        manifest = parse_manifest(manifest_path)
        assert manifest is not None
        assert manifest.module_name == "custom_module"
        assert manifest.name == "Test Module"
        assert manifest.depends == ["base", "sale"]
        assert manifest.data == ["security/ir.model.access.csv", "views/test_views.xml"]
        assert manifest.installable is True

        # Check unloaded file detection
        assert "views/orphan_view.xml" in manifest.unloaded_data_files


def test_real_manifest_miro_ai():
    """Test parsing real manifest from odoo17-dev/addons/miro_ai/__manifest__.py."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    addons_dir = CORE_ADDONS_PATH if CORE_ADDONS_PATH.exists() else root_dir / "addons"
    real_manifest = addons_dir / "miro_ai" / "__manifest__.py"

    if real_manifest.exists():
        manifest = parse_manifest(real_manifest)
        assert manifest is not None
        assert manifest.module_name == "miro_ai"
        assert manifest.name == "MIRO AI Assistant"
        assert manifest.depends == ["base"]
        assert "security/ir.model.access.csv" in manifest.data
        assert "views/miro_ai_settings_views.xml" in manifest.data
