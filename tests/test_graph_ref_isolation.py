import pytest

import code_intelligence.agent.tool_helpers as tool_helpers

SENTINEL = object()


def test_isolation_fixture_is_active(request):
    assert "_isolate_tool_helpers_graph_ref" in request.fixturenames


class TestGraphRefDoesNotLeak:
    def test_a_sets_a_graph_ref(self):
        tool_helpers.set_graph_ref(SENTINEL)
        assert tool_helpers.get_graph_ref() is SENTINEL

    def test_b_does_not_inherit_it(self):
        assert tool_helpers.get_graph_ref() is not SENTINEL


@pytest.fixture(scope="module")
def module_graph():
    previous = tool_helpers.get_graph_ref()
    marker = object()
    tool_helpers.set_graph_ref(marker)
    yield marker
    tool_helpers.set_graph_ref(previous)


class TestModuleScopedGraphIsKept:
    def test_first_test_sees_the_module_graph(self, module_graph):
        assert tool_helpers.get_graph_ref() is module_graph

    def test_second_test_still_sees_it(self, module_graph):
        assert tool_helpers.get_graph_ref() is module_graph
