"""
code_intelligence/tests/test_section922_scoped_source_reader.py

Source reader resolves configured files without escaping addon roots.
"""


from code_intelligence.agent.tools.introspection import read_precise_source_code


class TestScopedSourceReader:
    def test_bare_filename_resolves_to_native_not_tests(self):
        # res_company.py exists in both core addons and in tests/oca_sample/
        res = read_precise_source_code("res_company.py", 1, 20, include_citation=True)
        assert not res.startswith("Error")
        assert "tests/oca_sample" not in res
        assert "addons/" in res


def test_source_under_a_graph_addon_root_is_readable(tmp_path):
    import networkx as nx

    import code_intelligence.agent.tools.helpers as tool_helpers

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
