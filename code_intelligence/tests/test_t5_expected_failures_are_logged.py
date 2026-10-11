import ast
import logging
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest

from code_intelligence.graph.staleness import compute_file_hash
from code_intelligence.rules.security_locks import _extract_has_group_xmlids_from_source
from code_intelligence.rules.structure import _extract_ast_class_info
from code_intelligence.rules.xml_view_finder import _resolve_field_name_from_view_string_override
from code_intelligence.utils import parse_python_text, read_source_text


def _warnings(caplog):
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


def test_read_source_text_returns_the_text(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("x = 1\n", encoding="utf-8")
    assert read_source_text(source) == "x = 1\n"


def test_read_source_text_logs_a_missing_file(tmp_path, caplog):
    assert read_source_text(tmp_path / "absent.py") is None
    assert any("absent.py" in message for message in _warnings(caplog))


def test_read_source_text_logs_undecodable_bytes(tmp_path, caplog):
    source = tmp_path / "latin1.py"
    source.write_bytes("caf\xe9".encode("latin-1"))
    assert read_source_text(source) is None
    assert any("latin1.py" in message for message in _warnings(caplog))


def test_parse_python_text_returns_a_module():
    assert isinstance(parse_python_text("x = 1\n", "a.py"), ast.Module)


def test_parse_python_text_logs_a_syntax_error(caplog):
    assert parse_python_text("def broken(:\n", "broken.py") is None
    assert any("broken.py" in message for message in _warnings(caplog))


def test_compute_file_hash_logs_an_unreadable_path(tmp_path, caplog):
    assert compute_file_hash(tmp_path) == ""
    assert _warnings(caplog)


def test_security_locks_source_scan_logs_an_unreadable_file(tmp_path, caplog):
    with patch("code_intelligence.agent.tool_helpers.find_model_source_filepaths", return_value=[str(tmp_path)]):
        assert _extract_has_group_xmlids_from_source(nx.DiGraph(), "res.partner") == set()
    assert _warnings(caplog)


def test_security_locks_source_scan_still_reads_a_valid_file(tmp_path):
    source = tmp_path / "model.py"
    source.write_text("if self.env.user.has_group('base.group_system'):\n    pass\n", encoding="utf-8")
    with patch("code_intelligence.agent.tool_helpers.find_model_source_filepaths", return_value=[str(source)]):
        assert "base.group_system" in _extract_has_group_xmlids_from_source(nx.DiGraph(), "res.partner")


def test_class_info_extraction_logs_a_syntax_error(tmp_path, caplog):
    broken = tmp_path / "broken_model.py"
    broken.write_text("class A(:\n", encoding="utf-8")
    assert _extract_ast_class_info(str(broken), "res.partner") is None
    assert any("broken_model.py" in message for message in _warnings(caplog))


def test_view_scan_logs_a_malformed_xml_and_keeps_scanning(tmp_path, caplog):
    module_dir = tmp_path / "mod"
    views = module_dir / "views"
    views.mkdir(parents=True)
    (views / "bad.xml").write_text('<odoo string="x"><record', encoding="utf-8")
    graph = nx.DiGraph()
    graph.add_node("module:mod", node_type="Module", filepath=str(module_dir / "__manifest__.py"))
    assert _resolve_field_name_from_view_string_override(graph, "res.partner", "label") is None
    assert any("bad.xml" in message for message in _warnings(caplog))


def test_programming_errors_are_not_swallowed(tmp_path):
    views = tmp_path / "mod" / "views"
    views.mkdir(parents=True)
    (views / "ok.xml").write_text("<odoo string='x'></odoo>", encoding="utf-8")
    graph = nx.DiGraph()
    graph.add_node("module:mod", node_type="Module", filepath=str(tmp_path / "mod" / "__manifest__.py"))
    with patch("code_intelligence.rules.xml_view_finder.ET.fromstring", side_effect=AttributeError("bug")):
        with pytest.raises(AttributeError):
            _resolve_field_name_from_view_string_override(graph, "res.partner", "label")
