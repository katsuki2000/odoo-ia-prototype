"""
code_intelligence/tests/test_analyser_contraintes_donnees.py

 -> agent wiring: unit tests for analyze_data_constraints, the
tool exposing Semgrep-detected _sql_constraints / relational domain=
findings to the ReAct agent. Fills the gap noted during J14 .

Semgrep itself is NOT invoked here (no subprocess, no real .venv semgrep
binary dependency) -- code_intelligence.rules.data_constraints.run_semgrep_analysis
is monkeypatched to return canned SemgrepMatch objects, keeping this a
fast, deterministic unit test of the tool's own logic (graph lookup,
per-file dispatch, confidence tag, citation formatting), not an
integration test of Semgrep itself (that belongs to test_semgrep_runner.py
and the J11/J12 `semgrep --test` fixtures).
"""

from __future__ import annotations

import networkx as nx
import pytest

from code_intelligence.agent.tools import ALL_CI_TOOLS, analyze_data_constraints
from code_intelligence.agent.tool_helpers import find_model_source_filepaths, set_graph_ref
from code_intelligence.rules.data_constraints import (
    SemgrepMatch,
    _conditional_check_facts,
    backfill_missing_conditional_check_facts,
)


@pytest.fixture
def graph_with_model_file(tmp_path):
    """A minimal graph: one model with a field pointing to a real (empty)
    temp .py file, so find_model_source_filepaths resolves to a path that
    genuinely exists on disk (Path.exists() must be true for the tool to
    attempt analysis)."""
    py_file = tmp_path / "sale_order.py"
    py_file.write_text("# placeholder, content irrelevant -- semgrep is mocked\n")

    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order", filepaths=[])
    G.add_node("field:sale.order.payment_term_id", node_type="Field", filepath=str(py_file))
    G.add_edge("model:sale.order", "field:sale.order.payment_term_id", edge_type="HAS_FIELD")
    return G, py_file


@pytest.fixture(autouse=True)
def _reset_graph_ref():
    """Ensure no test leaks its graph into another via the module-level ref."""
    yield
    set_graph_ref(None)


def test_model_not_found_in_graph():
    G = nx.DiGraph()
    set_graph_ref(G)
    result = analyze_data_constraints.invoke({"model_name": "does.not.exist"})
    assert "was not found in the indexed knowledge graph" in result


def test_model_found_but_no_source_files():
    G = nx.DiGraph()
    G.add_node("model:empty.model", node_type="Model", name="empty.model", filepaths=[])
    set_graph_ref(G)
    result = analyze_data_constraints.invoke({"model_name": "empty.model"})
    assert "No Python source files located" in result


def test_no_patterns_detected_reports_high_confidence_deterministic(
    graph_with_model_file, monkeypatch
):
    G, _ = graph_with_model_file
    set_graph_ref(G)
    monkeypatch.setattr(
        "code_intelligence.rules.data_constraints.run_semgrep_analysis", lambda *a, **k: []
    )
    result = analyze_data_constraints.invoke({"model_name": "sale.order"})
    assert "No _sql_constraints or relational domain=" in result
    assert "[Confiance: ÉLEVÉE" in result
    assert "deterministic" in result.lower()


def test_single_match_includes_citation_and_check_id(graph_with_model_file, monkeypatch):
    G, py_file = graph_with_model_file
    match = SemgrepMatch(
        filepath=str(py_file),
        start_line=10,
        end_line=12,
        check_id="odoo-sql-constraints-declaration",
        message="Odoo _sql_constraints declaration detected.",
        lines="_sql_constraints = [('x_uniq', 'unique(x)', 'X must be unique')]",
    )
    set_graph_ref(G)
    monkeypatch.setattr(
        "code_intelligence.rules.data_constraints.run_semgrep_analysis", lambda *a, **k: [match]
    )
    result = analyze_data_constraints.invoke({"model_name": "sale.order"})

    assert "odoo-sql-constraints-declaration" in result
    assert "Odoo _sql_constraints declaration detected." in result
    assert f"file://{py_file}#L10-L12" in result
    assert "[Confiance: ÉLEVÉE" in result
    # the raw matched code should be surfaced, not just the message
    assert "_sql_constraints = [" in result


def test_multiple_matches_all_included_with_confidence_tag_once(
    graph_with_model_file, monkeypatch
):
    G, py_file = graph_with_model_file
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
    set_graph_ref(G)
    monkeypatch.setattr(
        "code_intelligence.rules.data_constraints.run_semgrep_analysis", lambda *a, **k: matches
    )
    result = analyze_data_constraints.invoke({"model_name": "sale.order"})

    assert "odoo-sql-constraints-declaration" in result
    assert "odoo-relational-domain-declaration" in result
    assert f"file://{py_file}#L5-L5" in result
    assert f"file://{py_file}#L20-L22" in result
    # Confidence tag is a property of the whole analysis, not repeated per finding
    assert result.count("[Confiance: ÉLEVÉE") == 1


def test_skips_filepaths_that_do_not_exist_on_disk(monkeypatch, tmp_path):
    """A filepath recorded in the graph but missing on disk (stale index,
    moved file) must be skipped silently, not crash the tool."""
    G = nx.DiGraph()
    missing_path = str(tmp_path / "gone.py")
    G.add_node("model:ghost.model", node_type="Model", name="ghost.model", filepaths=[missing_path])
    set_graph_ref(G)

    called = []
    monkeypatch.setattr(
        "code_intelligence.rules.data_constraints.run_semgrep_analysis",
        lambda *a, **k: called.append(a) or [],
    )
    result = analyze_data_constraints.invoke({"model_name": "ghost.model"})

    assert called == []  # never invoked on a nonexistent file
    assert "No _sql_constraints or relational domain=" in result


def test_uses_shared_find_model_source_filepaths_helper(graph_with_model_file):
    """Regression guard against the F-08 class of bug : the model-file
    lookup must be the single shared helper, not a second inline copy."""
    G, py_file = graph_with_model_file
    filepaths = find_model_source_filepaths(G, "sale.order")
    assert str(py_file) in filepaths


def test_registered_in_all_ci_tools():
    tool_names = {t.name for t in ALL_CI_TOOLS}
    assert "analyze_data_constraints" in tool_names


def test_ci_system_prompt_mentions_the_tool():
    from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT
    assert "analyze_data_constraints" in CI_SYSTEM_PROMPT


def test_conditional_check_fact_preserves_false_guard_semantics():
    match = SemgrepMatch(
        filepath="purchase_order_line.py",
        start_line=80,
        end_line=82,
        check_id="odoo-sql-constraints-declaration",
        message="SQL constraint.",
        lines=(
            "CHECK(display_type IS NOT NULL OR "
            "(product_id IS NOT NULL AND product_uom IS NOT NULL))"
        ),
    )

    facts = _conditional_check_facts(match)

    assert len(facts) == 1
    assert "display_type IS NOT NULL" in facts[0]
    assert "when `display_type IS NULL`" in facts[0]
    assert "Do not swap these branches" in facts[0]


def test_conditional_check_facts_extract_all_checks_from_one_constraint_declaration():
    match = SemgrepMatch(
        filepath="purchase_order_line.py",
        start_line=80,
        end_line=87,
        check_id="odoo-sql-constraints-declaration",
        message="SQL constraints.",
        lines=(
            "_sql_constraints = ["
            "('accountable_required_fields', "
            "'CHECK(display_type IS NOT NULL OR (product_id IS NOT NULL AND "
            "product_uom IS NOT NULL AND date_planned IS NOT NULL))', ''),"
            "('non_accountable_null_fields', "
            "'CHECK(display_type IS NULL OR (product_id IS NULL AND "
            "price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL "
            "AND date_planned IS NULL))', '')]"
        ),
    )

    facts = _conditional_check_facts(match)

    assert len(facts) == 2
    assert "when `display_type IS NULL`" in facts[0]
    assert "when `display_type IS NOT NULL`" in facts[1]


def test_backfill_missing_conditional_check_fields():
    evidence = (
        "[CHECK LOGIC] Exact branch mapping: this SQL CHECK is satisfied when "
        "either `display_type IS NULL` is true, or `product_id IS NULL AND "
        "price_unit = 0 AND product_uom_qty = 0` is true. Therefore, when "
        "`display_type IS NOT NULL`, `product_id IS NULL AND price_unit = 0 "
        "AND product_uom_qty = 0` must be true. Do not swap these branches."
    )

    answer = backfill_missing_conditional_check_facts(
        "La réponse mentionne seulement product_id.", evidence
    )

    assert "display_type IS NOT NULL" in answer
    assert "price_unit = 0" in answer


def test_backfill_corrects_ambiguous_branch_paraphrase():
    evidence = (
        "[CHECK LOGIC] Exact branch mapping: this SQL CHECK is satisfied when "
        "either `display_type IS NOT NULL` is true, or `product_id IS NOT NULL "
        "AND product_uom IS NOT NULL AND date_planned IS NOT NULL` is true. "
        "Therefore, when `display_type IS NULL`, `product_id IS NOT NULL AND "
        "product_uom IS NOT NULL AND date_planned IS NOT NULL` must be true."
    )

    answer = backfill_missing_conditional_check_facts(
        "Si display_type est nul, tous les champs sont non nuls.", evidence
    )

    assert "product_id IS NOT NULL AND product_uom IS NOT NULL" in answer


def test_backfill_uses_raw_check_when_logic_annotation_is_missing():
    raw_output = (
        "_sql_constraints = [('x', "
        "'CHECK(display_type IS NULL OR (price_unit = 0 AND "
        "product_uom_qty = 0))', '')]"
    )

    answer = backfill_missing_conditional_check_facts(
        "La réponse ne précise pas la branche.", raw_output
    )

    assert "display_type IS NOT NULL" in answer
    assert "price_unit = 0" in answer


def test_backfill_marks_multiple_branches_as_independent():
    evidence = (
        "[CHECK LOGIC] Exact branch mapping: when `display_type IS NULL`, "
        "`product_id IS NOT NULL` must be true.\n"
        "[CHECK LOGIC] Exact branch mapping: when `display_type IS NOT NULL`, "
        "`product_id IS NULL` must be true."
    )

    answer = backfill_missing_conditional_check_facts("Réponse.", evidence)

    assert "branches sont indépendantes" in answer


def test_backfill_skips_internal_sql_branch_detail_for_generic_constraint_question():
    evidence = (
        "[CHECK LOGIC] Exact branch mapping: when `state = 'sale'`, "
        "`date_order IS NOT NULL` must be true."
    )
    answer = backfill_missing_conditional_check_facts(
        "La date est obligatoire quand la commande est confirmée.",
        evidence,
        question="Quelle contrainte empêche une commande confirmée de ne pas avoir de date ?",
    )
    assert answer == "La date est obligatoire quand la commande est confirmée."


def test_backfill_keeps_exact_sql_detail_when_question_requests_sql():
    evidence = (
        "[CHECK LOGIC] Exact branch mapping: when `state = 'sale'`, "
        "`date_order IS NOT NULL` must be true."
    )
    answer = backfill_missing_conditional_check_facts(
        "La commande confirmée doit avoir une date.",
        evidence,
        question="Quelle contrainte SQL impose cette règle ?",
    )
    assert "date_order IS NOT NULL" in answer
