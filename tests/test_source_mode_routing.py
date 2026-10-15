"""The user may force documentation/system; without a choice the LLM classifies the source."""

from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from api.schemas import AskRequestV1
from code_intelligence.agent.investigation_schemas import QuestionIntent
from code_intelligence.agent.loop import code_intelligence_agent
from core.graph.graph_nodes import ci_evidence_decision
from core.routing.routing import route, route_decision
from core.schemas import QueryRoute


@dataclass
class _Concept:
    user_term: str = ""
    resolved_models: List[str] = field(default_factory=list)
    is_resolved: bool = False


def _patched_pipeline(intent=QuestionIntent.DOCUMENTARY_POLICY):
    """Patch resolver, graph loader, intent classifier and planner (no graph, no LLM)."""
    stack = ExitStack()
    resolver = stack.enter_context(
        patch("code_intelligence.agent.resolver.resolve_business_term", return_value=_Concept())
    )
    stack.enter_context(patch("code_intelligence.graph.loader.get_code_intelligence_graph", return_value=MagicMock()))
    stack.enter_context(
        patch("core.routing.routing.resolve_question_intent", return_value=MagicMock(intent=intent, source="test"))
    )
    plan = MagicMock()
    plan.to_display_dict.return_value = {}
    stack.enter_context(patch("core.routing.routing.generate_investigation_plan", return_value=plan))
    stack.enter_context(patch("core.routing.routing.validate_plan_against_route", return_value=plan))
    return stack, resolver


def _state(question, **extra):
    state = {"question": question, "timing": {}, "chat_history": []}
    state.update(extra)
    return state


def test_documentation_mode_short_circuits_route():
    """Mode documentation: ni resolveur, ni classifieur d'intention."""
    stack, resolver = _patched_pipeline()
    with stack:
        result = route(_state(
            "quelles sont les regles a respecter quand on code d'apres la documentation?",
            source_mode="documentation",
        ))
    resolver.assert_not_called()
    assert result["route"] == QueryRoute.DOCUMENTAIRE.value
    assert result["investigation_plan"] is None
    assert result["resolved_concept"] is None


def test_route_decision_ignores_source_mode():
    """La topologie du graphe ne change pas : route_decision() renvoie toujours la route calculee."""
    for mode in (None, "documentation", "systeme"):
        assert route_decision({"route": QueryRoute.DONNEES_ERP.value, "source_mode": mode}) == QueryRoute.DONNEES_ERP.value
        assert route_decision({"route": QueryRoute.DOCUMENTAIRE.value, "source_mode": mode}) == QueryRoute.DOCUMENTAIRE.value


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


def test_no_mode_keeps_documentary_route():
    stack, _ = _patched_pipeline()
    with stack:
        result = route(_state("regles de codage defensif"))
    assert result["route"] == QueryRoute.DOCUMENTAIRE.value


def test_systeme_mode_remaps_documentary_to_code_intelligence():
    stack, _ = _patched_pipeline()
    with stack:
        result = route(_state("regles de codage defensif", source_mode="systeme"))
    assert result["route"] == QueryRoute.CODE_INTELLIGENCE.value


def test_systeme_mode_remaps_documentary_to_erp_when_data_term():
    stack, _ = _patched_pipeline()
    with stack:
        result = route(_state("liste des ventes", source_mode="systeme"))
    assert result["route"] == QueryRoute.DONNEES_ERP.value


def test_systeme_mode_leaves_non_documentary_route_alone():
    stack, _ = _patched_pipeline(intent=QuestionIntent.GOVERNANCE_SECURITY)
    with stack:
        result = route(_state("qui peut modifier une commande?", source_mode="systeme"))
    assert result["route"] == QueryRoute.CODE_INTELLIGENCE.value


def test_ask_request_source_mode_validation():
    base = dict(question="q", session_id="s", user_uid=1, company_id=1)
    assert AskRequestV1(**base).source_mode is None
    assert AskRequestV1(**base, source_mode="documentation").source_mode == "documentation"
    with pytest.raises(ValidationError):
        AskRequestV1(**base, source_mode="autre")
