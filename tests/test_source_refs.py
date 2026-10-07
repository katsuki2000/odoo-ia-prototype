"""Hermetic tests for the code-graph source reference format."""

from core.evidence.source_refs import CodeGraphSource, format_code_graph_source, parse_code_graph_source


def test_format_and_parse_round_trip():
    source = format_code_graph_source("who_has_access_to", "account.move")
    assert source == "code_intelligence:who_has_access_to:account.move"
    assert parse_code_graph_source(source) == CodeGraphSource("who_has_access_to", "account.move")


def test_missing_parts_are_written_as_unknown_and_parsed_as_none():
    source = format_code_graph_source(None, None)
    assert source == "code_intelligence:unknown:unknown"
    assert parse_code_graph_source(source) == CodeGraphSource("unknown", None)


def test_foreign_or_empty_sources_are_not_code_graph_sources():
    assert parse_code_graph_source("guide.pdf") is None
    assert parse_code_graph_source("") is None
    assert parse_code_graph_source(None) is None
