"""
miro-rag/code_intelligence/tests/test_analyser_contraintes_donnees.py

Unit tests for analyser_contraintes_donnees tool (ci_agent_tools.py).
"""

from unittest.mock import MagicMock, patch
from pathlib import Path
from code_intelligence.ci_agent_tools import (
    find_model_source_filepaths,
    analyser_contraintes_donnees,
)


def test_find_model_source_filepaths():
    G = MagicMock()
    G.__contains__.side_effect = lambda node: node == "model:sale.order"
    G.nodes = {
        "model:sale.order": {"filepaths": ["/path/to/sale_order.py"]},
    }
    paths = find_model_source_filepaths(G, "sale.order")
    assert paths == {"/path/to/sale_order.py"}


@patch("code_intelligence.ci_agent_tools._require_graph")
@patch("code_intelligence.ci_agent_tools.find_model_source_filepaths")
@patch("code_intelligence.semgrep_runner.run_semgrep_analysis")
def test_analyser_contraintes_donnees_tool(mock_semgrep, mock_find_paths, mock_graph):
    G = MagicMock()
    G.__contains__.side_effect = lambda node: node == "model:sale.order"
    mock_graph.return_value = G
    mock_find_paths.return_value = {"/path/to/sale_order.py"}

    mock_match = MagicMock()
    mock_match.filepath = "/path/to/sale_order.py"
    mock_match.start_line = 10
    mock_match.end_line = 15
    mock_match.check_id = "odoo-sql-constraints-declaration"
    mock_match.message = "Odoo model defines SQL constraints"
    mock_match.lines = "_sql_constraints = [('uniq_code', 'unique(code)', 'msg')]"

    mock_semgrep.return_value = [mock_match]

    with patch.object(Path, "exists", return_value=True):
        res = analyser_contraintes_donnees.invoke({"model_name": "sale.order"})
        assert "Analyse des contraintes de données (Semgrep)" in res
        assert "odoo-sql-constraints-declaration" in res
        assert "file:///path/to/sale_order.py#L10-L15" in res
