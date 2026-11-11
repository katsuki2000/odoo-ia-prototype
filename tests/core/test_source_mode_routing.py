"""The user always chooses the source ('documentation' or 'system'); the pipeline never picks it."""

import pytest
from pydantic import ValidationError

from api.schemas import AskRequestV1
from core.graph.graph import build_graph, query_graph


def test_ask_request_requires_a_valid_source_mode():
    base = {"question": "q", "session_id": "s", "company_id": 1}
    assert AskRequestV1(**base, source_mode="documentation").source_mode == "documentation"
    assert AskRequestV1(**base, source_mode="system").source_mode == "system"
    with pytest.raises(ValidationError):
        AskRequestV1(**base)
    with pytest.raises(ValidationError):
        AskRequestV1(**base, source_mode="autre")


@pytest.mark.parametrize("source_mode", [None, "", "autre"])
def test_query_graph_rejects_an_unknown_source_mode(source_mode):
    with pytest.raises(ValueError):
        query_graph("q", source_mode)


def test_graph_starts_on_the_branch_of_the_chosen_source():
    edges = build_graph().get_graph().edges
    assert {edge.target for edge in edges if edge.source == "__start__"} == {"retrieve", "orm_agent_loop"}
