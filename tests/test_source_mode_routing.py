"""The user may force documentation/system; without a choice the LLM classifies the source."""

from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from api.schemas import AskRequestV1
from code_intelligence.agent.loop import code_intelligence_agent
from core.graph.graph_nodes import ci_evidence_decision
from core.routing.routing import route, route_decision
from core.schemas import QueryRoute


def test_route_decision_ignores_source_mode():
    """La topologie du graphe ne change pas : route_decision() renvoie toujours la route calculee."""
    for mode in (None, "documentation", "systeme"):
        assert route_decision({"route": QueryRoute.ERP_DATA.value, "source_mode": mode}) == QueryRoute.ERP_DATA.value
        assert route_decision({"route": QueryRoute.DOCUMENTARY.value, "source_mode": mode}) == QueryRoute.DOCUMENTARY.value


def test_ci_agent_node_skipped_in_documentation_mode():
    with patch("code_intelligence.agent.loop.CodeIntelligenceAgentRunner") as runner:
        out = code_intelligence_agent({"question": "q", "source_mode": "documentation", "timing": {"routing_time": 0.1}})
    runner.assert_not_called()
    assert out == {"timing": {"routing_time": 0.1}}


def test_ci_agent_node_runs_without_documentation_mode():
    for mode in (None, "systeme"):
        with patch("code_intelligence.agent.loop.CodeIntelligenceAgentRunner") as runner:
            runner.return_value.run.return_value = {"raw_answer": "x"}
            out = code_intelligence_agent({"question": "q", "source_mode": mode})
        runner.assert_called_once()
        assert out == {"raw_answer": "x"}


def test_ci_evidence_decision_documentation_goes_to_generate():
    assert ci_evidence_decision({"source_mode": "documentation"}) == "generate"
    assert ci_evidence_decision({"source_mode": "documentation", "ci_evidence_sufficiency": {"status": "sufficient"}}) == "generate"
    assert ci_evidence_decision({}) == "format_output"


def test_ask_request_source_mode_validation():
    base = dict(question="q", session_id="s", user_uid=1, company_id=1)
    assert AskRequestV1(**base).source_mode is None
    assert AskRequestV1(**base, source_mode="documentation").source_mode == "documentation"
    with pytest.raises(ValidationError):
        AskRequestV1(**base, source_mode="autre")
