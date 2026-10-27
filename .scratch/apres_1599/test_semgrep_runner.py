"""
miro-rag/code_intelligence/tests/test_semgrep_runner.py

Unit test for semgrep_runner.py.
Verifies subprocess execution of Semgrep with --json output and structured SemgrepMatch parsing.
"""

from pathlib import Path
from code_intelligence.rules.data_constraints import run_semgrep_analysis


def test_semgrep_runner_sql_constraints():
    base_dir = Path(__file__).resolve().parent.parent / "semgrep_rules"
    config_path = base_dir / "sql_constraints.yaml"
    target_path = base_dir / "sql_constraints.py"

    matches = run_semgrep_analysis([target_path], config_path)
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

    matches = run_semgrep_analysis([target_path], config_path)
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


def test_semgrep_runner_raw_sql_unique_constraints():
    """todo/contexte.txt section 811/812 : analyze_data_constraints ne
    detectait aucun mecanisme d'unicite SQL brut (CREATE UNIQUE INDEX via
    .execute(...), ou l'helper odoo.tools.sql.create_unique_index()) --
    seule la declaration _sql_constraints (parfois a chaine SQL vide,
    comme sur account.move) etait vue, poussant le LLM a inventer un
    mecanisme Python inexistant. Les 2 nouvelles regles comblent ce trou."""
    base_dir = Path(__file__).resolve().parent.parent / "semgrep_rules"
    config_path = base_dir / "raw_sql_constraints.yaml"
    target_path = base_dir / "raw_sql_constraints.py"

    matches = run_semgrep_analysis([target_path], config_path)
    assert len(matches) == 2

    check_ids = {m.check_id.rsplit(".", 1)[-1] for m in matches}
    assert check_ids == {"odoo-raw-sql-unique-index", "odoo-create-unique-index-helper"}

    # odoo-raw-sql-unique-index : le cas type account.move (CREATE UNIQUE
    # INDEX dans une chaine multi-lignes passee a .execute(...)).
    unique_index_match = next(
        m for m in matches if m.check_id.endswith("odoo-raw-sql-unique-index")
    )
    assert "CREATE UNIQUE INDEX" in unique_index_match.lines
    assert "account_move_unique_name" in unique_index_match.lines

    # odoo-create-unique-index-helper : l'appel a l'helper odoo.tools.sql.
    helper_match = next(
        m for m in matches if m.check_id.endswith("odoo-create-unique-index-helper")
    )
    assert "create_unique_index" in helper_match.lines

    # Faux positifs a exclure explicitement (annotes `ok:` dans le fixture) :
    # CREATE INDEX simple (non-unique), .execute() sans rapport avec du SQL,
    # et create_index() (l'helper NON-unique).
    matched_text = " ".join(m.lines for m in matches)
    assert "stock_move_state_idx" not in matched_text
    assert "wizard.execute" not in matched_text
    assert "purchase_order_line_custom_idx" not in matched_text
