"""
miro-rag/code_intelligence/tests/test_semgrep_runner.py

Unit test for semgrep_runner.py.
Verifies subprocess execution of Semgrep with --json output and structured SemgrepMatch parsing.
"""

from pathlib import Path
from code_intelligence.data_constraints.runner import run_semgrep_analysis


def test_semgrep_runner_sql_constraints():
    base_dir = Path(__file__).resolve().parent.parent / "semgrep_rules"
    config_path = base_dir / "sql_constraints.yaml"
    target_path = base_dir / "sql_constraints.py"

    matches = run_semgrep_analysis(target_path, config_path)
    assert len(matches) == 2

    check_ids = [m.check_id for m in matches]
    assert all("odoo-sql-constraints-declaration" in cid for cid in check_ids)

    # Check line numbers and file paths
    assert all(m.filepath.endswith("sql_constraints.py") for m in matches)
    assert all(m.start_line > 0 for m in matches)


def test_semgrep_runner_domain_relational():
    base_dir = Path(__file__).resolve().parent.parent / "semgrep_rules"
    config_path = base_dir / "domain_relational.yaml"
    target_path = base_dir / "domain_relational.py"

    matches = run_semgrep_analysis(target_path, config_path)
    assert len(matches) == 4

    check_ids = [m.check_id for m in matches]
    assert all("odoo-relational-domain-declaration" in cid for cid in check_ids)

    # Verify matched field names
    matched_text = " ".join(m.lines for m in matches)
    assert "partner_id" in matched_text
    assert "category_ids" in matched_text
    assert "string_domain_partner_id" in matched_text
    # Simple and lambda fields should NOT be matched
    assert "simple_partner_id" not in matched_text
    assert "lambda_partner_id" not in matched_text
