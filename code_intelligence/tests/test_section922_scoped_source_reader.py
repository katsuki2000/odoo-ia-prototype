"""
code_intelligence/tests/test_section922_scoped_source_reader.py

Tests for Section 922:
1. read_precise_source_code resolves bare filenames to native/custom addons,
   never to tests/ fixture directories.
2. _GRAPH_REF priority resolution for model stems.
3. _PROSE_LINE_CLAIM_PATTERN properly recognizes unicode non-breaking hyphens (U+2011).
"""


from code_intelligence.agent.dispatch_guards import _PROSE_LINE_CLAIM_PATTERN
from code_intelligence.agent.tools.introspection import read_precise_source_code
import code_intelligence.agent.tool_helpers as th


class TestProseLineClaimUnicodeDashes:
    def test_ascii_hyphen_range(self):
        text = "`purchase.order` (lignes 18-98)"
        m = _PROSE_LINE_CLAIM_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "purchase.order"
        assert m.group(2) == "18"
        assert m.group(3) == "98"

    def test_unicode_non_breaking_hyphen_range(self):
        # U+2011 (non-breaking hyphen)
        text = "`purchase.order` est créé dans le fichier **purchase_order.py** (ligne 18\u201198)"
        m = _PROSE_LINE_CLAIM_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "purchase.order"
        assert m.group(2) == "18"
        assert m.group(3) == "98"

    def test_en_dash_range(self):
        # U+2013 (en-dash)
        text = "`sale.order` (lignes 10\u201350)"
        m = _PROSE_LINE_CLAIM_PATTERN.search(text)
        assert m is not None
        assert m.group(2) == "10"
        assert m.group(3) == "50"


class TestScopedSourceReader:
    def test_bare_filename_resolves_to_native_not_tests(self):
        # res_company.py exists in both core addons and in tests/oca_sample/
        res = read_precise_source_code("res_company.py", 1, 20, include_citation=True)
        assert not res.startswith("Error")
        assert "tests/oca_sample" not in res
        assert "addons/" in res


def test_source_under_a_graph_addon_root_is_readable(tmp_path):
    import networkx as nx

    import code_intelligence.agent.tool_helpers as tool_helpers

    source = tmp_path / "framework_addons" / "base" / "models" / "res_company.py"
    source.parent.mkdir(parents=True)
    source.write_text("class ResCompany:\n    pass\n", encoding="utf-8")
    graph = nx.DiGraph()
    graph.graph["addon_roots_ordered"] = [str(tmp_path / "framework_addons")]
    previous = tool_helpers.get_graph_ref()
    tool_helpers.set_graph_ref(graph)
    try:
        result = read_precise_source_code(str(source), 1, 2)
    finally:
        tool_helpers.set_graph_ref(previous)
    assert not result.startswith("Error")
    assert "class ResCompany" in result
