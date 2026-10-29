"""The user may force documentation/system; without a choice the LLM classifies the source."""

import pytest
from pydantic import ValidationError

from api.schemas import AskRequestV1
from core.routing.routing import route_decision
from core.schemas import QueryRoute


def test_route_decision_ignores_source_mode():
    """La topologie du graphe ne change pas : route_decision() renvoie toujours la route calculee."""
    for mode in (None, "documentation", "system"):
        assert route_decision({"route": QueryRoute.ERP_DATA.value, "source_mode": mode}) == QueryRoute.ERP_DATA.value
        assert route_decision({"route": QueryRoute.DOCUMENTARY.value, "source_mode": mode}) == QueryRoute.DOCUMENTARY.value


def test_ask_request_source_mode_validation():
    base = dict(question="q", session_id="s", company_id=1)
    assert AskRequestV1(**base).source_mode is None
    assert AskRequestV1(**base, source_mode="documentation").source_mode == "documentation"
    with pytest.raises(ValidationError):
        AskRequestV1(**base, source_mode="autre")
