import pytest

from core.graph import graph as graph_module
from core.schemas import AssistantResponse
from erp_data.odoo_context import (
    odoo_api_key_ctx,
    odoo_company_id_ctx,
    odoo_company_ids_ctx,
    odoo_db_ctx,
    odoo_uid_ctx,
    request_identity,
)


def _identity():
    return (
        odoo_uid_ctx.get(), odoo_api_key_ctx.get(), odoo_company_id_ctx.get(),
        odoo_company_ids_ctx.get(), odoo_db_ctx.get(),
    )


class _FakeGraph:
    def __init__(self, failure=None):
        self.failure = failure
        self.identities = []

    def invoke(self, state):
        self.identities.append(_identity())
        if self.failure:
            raise self.failure
        return {'response': AssistantResponse(answer='ok', confidence=1.0), 'timing': {}}


@pytest.fixture
def fake_graph(monkeypatch):
    fake = _FakeGraph()
    monkeypatch.setattr(graph_module, 'build_graph', lambda: fake)
    graph_module._compiled_graph.cache_clear()
    yield fake
    graph_module._compiled_graph.cache_clear()


def test_graph_is_compiled_once(monkeypatch):
    builds = []
    monkeypatch.setattr(graph_module, 'build_graph', lambda: builds.append(1) or _FakeGraph())
    graph_module._compiled_graph.cache_clear()
    graph_module.query_graph('q1')
    graph_module.query_graph('q2')
    graph_module._compiled_graph.cache_clear()
    assert len(builds) == 1


def test_identity_is_bound_during_the_call_and_reset_after(fake_graph):
    response = graph_module.query_graph('q', uid=7, api_key='key', company_id=2, db='shop')
    assert response.answer == 'ok'
    assert fake_graph.identities == [(7, 'key', 2, [2], 'shop')]
    assert _identity() == (None, None, None, None, None)


def test_pipeline_failure_reaches_the_caller_and_identity_is_reset(fake_graph):
    fake_graph.failure = ConnectionError('inference server down')
    with pytest.raises(ConnectionError):
        graph_module.query_graph('q', uid=7, api_key='key', company_id=2, db='shop')
    assert _identity() == (None, None, None, None, None)


def test_nested_request_does_not_inherit_the_outer_identity():
    with request_identity(1, 'outer', 3, [3, 4], 'outer_db'):
        with request_identity(None, None):
            assert _identity() == (None, None, None, None, None)
        assert _identity() == (1, 'outer', 3, [3, 4], 'outer_db')
    assert _identity() == (None, None, None, None, None)
