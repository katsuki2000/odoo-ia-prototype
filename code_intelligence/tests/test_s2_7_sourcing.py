"""
code_intelligence/tests/test_s2_7_sourcing.py

Unit tests for Structural Sourcing & File+Line Traceability.
Ensures deterministic tools and security analyzers include clickable file links
and line references in markdown format [file.py:L12-34](file:///abs/path#L12-L34).
"""

import pytest
from pathlib import Path
from code_intelligence.utils import format_file_link
from code_intelligence.rules.security import analyze_python_security_locks
from code_intelligence.rules.server_actions import analyze_server_action_code


class TestStructuralSourcing:
    def test_format_file_link_with_line_numbers(self):
        """Test formatting file path and line numbers into markdown link."""
        link = format_file_link("/home/user/addons/custom_module/models/test.py", start_line=12, end_line=25)
        assert "[test.py:L12-L25]" in link
        assert "(file:///home/user/addons/custom_module/models/test.py#L12-L25)" in link

    def test_format_file_link_without_line_numbers(self):
        """Test formatting file path without line numbers."""
        link = format_file_link("/home/user/addons/custom_module/security/rules.xml")
        assert "[rules.xml]" in link
        assert "(file:///home/user/addons/custom_module/security/rules.xml)" in link

    def test_semgrep_locks_includes_file_link(self, tmp_path):
        """Test that Python security lock analyzer output contains formatted file links."""
        p = tmp_path / "test_model.py"
        p.write_text("from odoo import models\nimport re\nclass Test(models.Model):\n    _VALIDATEURS = ['boss@co.com']\n", encoding="utf-8")

        analysis = analyze_python_security_locks(p.read_text(encoding="utf-8"), str(p))
        assert "file://" in analysis.summary_text
        assert "[test_model.py" in analysis.summary_text
