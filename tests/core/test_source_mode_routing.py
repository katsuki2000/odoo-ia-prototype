"""The user always chooses the source ('documents' or 'system'); the pipeline never picks it."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from api.routes.ask import _answer_question
from api.schemas import AskRequestV1
from core.graph.graph import build_graph, query_graph
from core.schemas import AssistantResponse


def test_ask_request_requires_a_valid_source_mode():
    base = {"question": "q", "session_id": "s", "company_id": 1}
    assert AskRequestV1(**base, source_mode="documents").source_mode == "documents"
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


def test_the_graph_receives_the_route_as_a_plain_string():
    request = AskRequestV1(question="q", session_id="s", company_id=1, source_mode="documents")
    with patch("api.routes.ask.get_session", return_value=[]), patch("api.routes.ask.update_session"), \
            patch("api.routes.ask.query_graph") as graph:
        graph.return_value = AssistantResponse(answer="a", confidence=0.5, route="documents")
        _answer_question(request, None, {"uid": 1, "api_key": "k"})
    assert type(graph.call_args.kwargs["source_mode"]) is str
