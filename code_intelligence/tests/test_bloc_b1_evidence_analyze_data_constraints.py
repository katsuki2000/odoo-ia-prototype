"""
code_intelligence/tests/test_bloc_b1_evidence_analyze_data_constraints.py

Tool 10/24, 2/5 Auxiliaire CI (todo/contexte.txt sections 463-464):
Evidence for analyze_data_constraints, backed by
code_intelligence/data_constraints_analyzer.py.

Two arbitrated decisions under direct test here (section 464):
  1. Evidence is built ONLY from real SemgrepMatch results -- an empty
     match list NEVER produces a fabricated negative Evidence, since
     run_semgrep_analysis() cannot currently distinguish "genuinely no
     findings" from "Semgrep execution failed" (both return []).
  2. summary_text (the public @tool contract) is strictly unchanged --
     covered by test_analyze_data_constraints.py, not duplicated here.
"""

from __future__ import annotations

import pytest

from code_intelligence.knowledge_rules.data_constraints.analyzer import (
    DataConstraintsAnalysis,
    analyze_data_constraints_from_filepaths,
)
from code_intelligence.knowledge_rules.data_constraints.runner import SemgrepMatch
from core.evidence.evidence import EvidenceSourceType


@pytest.fixture
def py_file(tmp_path):
    f = tmp_path / "sale_order.py"
    f.write_text("# placeholder, content irrelevant -- semgrep is mocked\n")
    return f


def test_empty_matches_produce_no_evidence(py_file, monkeypatch):
    """Core arbitrated decision (section 464): [] from Semgrep never becomes
    a fabricated negative Evidence, since it may mean either 'genuinely no
    findings' or 'Semgrep execution failed' -- indistinguishable today."""
    monkeypatch.setattr(
        "code_intelligence.knowledge_rules.data_constraints.runner.run_semgrep_analysis", lambda *a, **k: []
    )
    result = analyze_data_constraints_from_filepaths("sale.order", [str(py_file)])
    assert result.evidence == []
    # summary_text keeps asserting the ELEVEE confidence tag -- that is the
    # pre-existing public text contract, untouched by this Evidence work
    # (section 464), only reformatted via core.output.confidence_tags (section 629).
    assert "[Confiance: ÉLEVÉE" in result.summary_text


def test_single_match_produces_one_high_confidence_evidence(py_file, monkeypatch):
    match = SemgrepMatch(
        filepath=str(py_file), start_line=10, end_line=12,
        check_id="odoo-sql-constraints-declaration",
        message="Odoo _sql_constraints declaration detected.",
        lines="_sql_constraints = [('x_uniq', 'unique(x)', 'X must be unique')]",
    )
    monkeypatch.setattr(
        "code_intelligence.knowledge_rules.data_constraints.runner.run_semgrep_analysis", lambda *a, **k: [match]
    )
    result = analyze_data_constraints_from_filepaths("sale.order", [str(py_file)])

    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.source_type == EvidenceSourceType.CODE
    assert ev.confidence == "HIGH"
    assert "odoo-sql-constraints-declaration" in ev.claim
    assert str(py_file) in ev.claim
    assert ev.value == match.lines
    assert ev.source == f"data_constraints:{py_file}:odoo-sql-constraints-declaration:10"
    assert ev.scope == {"lineno": 10, "end_lineno": 12}


def test_multiple_matches_produce_one_evidence_each_with_correct_check_id(py_file, monkeypatch):
    """check_id already distinguishes SQL constraint vs relational domain=
    findings -- no separate classification layer is rebuilt (section 464)."""
    matches = [
        SemgrepMatch(
            filepath=str(py_file), start_line=5, end_line=5,
            check_id="odoo-sql-constraints-declaration",
            message="SQL constraint.", lines="_sql_constraints = [...]",
        ),
        SemgrepMatch(
            filepath=str(py_file), start_line=20, end_line=22,
            check_id="odoo-relational-domain-declaration",
            message="Relational domain on partner_id.", lines="partner_id = fields.Many2one(...)",
        ),
    ]
    monkeypatch.setattr(
        "code_intelligence.knowledge_rules.data_constraints.runner.run_semgrep_analysis", lambda *a, **k: matches
    )
    result = analyze_data_constraints_from_filepaths("sale.order", [str(py_file)])

    assert len(result.evidence) == 2
    check_ids = {ev.claim.split(" has a ")[1].split(" finding")[0] for ev in result.evidence}
    assert check_ids == {"odoo-sql-constraints-declaration", "odoo-relational-domain-declaration"}
    assert all(ev.confidence == "HIGH" for ev in result.evidence)
    scopes = sorted((ev.scope["lineno"], ev.scope["end_lineno"]) for ev in result.evidence)
    assert scopes == [(5, 5), (20, 22)]


def test_evidence_id_deterministic_across_identical_calls(py_file, monkeypatch):
    match = SemgrepMatch(
        filepath=str(py_file), start_line=10, end_line=12,
        check_id="odoo-sql-constraints-declaration",
        message="Odoo _sql_constraints declaration detected.",
        lines="_sql_constraints = [...]",
    )
    monkeypatch.setattr(
        "code_intelligence.knowledge_rules.data_constraints.runner.run_semgrep_analysis", lambda *a, **k: [match]
    )
    r1 = analyze_data_constraints_from_filepaths("sale.order", [str(py_file)])
    r2 = analyze_data_constraints_from_filepaths("sale.order", [str(py_file)])
    assert r1.evidence[0].evidence_id == r2.evidence[0].evidence_id


def test_nonexistent_filepath_skipped_no_evidence(tmp_path, monkeypatch):
    missing = tmp_path / "gone.py"
    called = []
    monkeypatch.setattr(
        "code_intelligence.knowledge_rules.data_constraints.runner.run_semgrep_analysis",
        lambda *a, **k: called.append(a) or [],
    )
    result = analyze_data_constraints_from_filepaths("ghost.model", [str(missing)])
    assert called == []
    assert result.evidence == []
    assert result.matches == []


def test_returns_dataclass_with_matches_field(py_file, monkeypatch):
    match = SemgrepMatch(
        filepath=str(py_file), start_line=10, end_line=12,
        check_id="odoo-sql-constraints-declaration",
        message="msg", lines="code",
    )
    monkeypatch.setattr(
        "code_intelligence.knowledge_rules.data_constraints.runner.run_semgrep_analysis", lambda *a, **k: [match]
    )
    result = analyze_data_constraints_from_filepaths("sale.order", [str(py_file)])
    assert isinstance(result, DataConstraintsAnalysis)
    assert result.matches == [match]
    assert result.model_name == "sale.order"


def test_summary_text_unaffected_by_evidence_presence(py_file, monkeypatch):
    """Regression guard: building Evidence must not alter summary_text --
    same composition function feeds both, but they are independent fields."""
    match = SemgrepMatch(
        filepath=str(py_file), start_line=5, end_line=5,
        check_id="odoo-sql-constraints-declaration",
        message="SQL constraint.", lines="_sql_constraints = [...]",
    )
    monkeypatch.setattr(
        "code_intelligence.knowledge_rules.data_constraints.runner.run_semgrep_analysis", lambda *a, **k: [match]
    )
    result = analyze_data_constraints_from_filepaths("sale.order", [str(py_file)])
    assert "odoo-sql-constraints-declaration" in result.summary_text
    assert result.summary_text.count("[Confiance: ÉLEVÉE") == 1
