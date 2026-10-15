"""Routing follows the current classifier result; it does not reuse a previous source route."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import patch

from code_intelligence.agent.investigation_schemas import QuestionIntent
from core.routing.routing import route
from core.schemas import QueryRoute


@dataclass
class _Concept:
    user_term: str = ""
    resolved_models: list[str] | None = None
    resolved_modules: list[str] | None = None
    is_resolved: bool = False
    source_step: str = "unresolved"
    confidence: float = 0.0
    reason: str = ""
    diagnostics: dict = field(default_factory=dict)


def _route(question, intent, **state_overrides):
    state = {"question": question, "timing": {}, "chat_history": []}
    state.update(state_overrides)
    plan = SimpleNamespace(to_display_dict=lambda: {})
    with (
        patch("core.routing.routing.resolve_question_intent", return_value=SimpleNamespace(intent=intent, source="llm")),
        patch("code_intelligence.graph.loader.get_code_intelligence_graph"),
        patch("code_intelligence.agent.resolver.resolve_business_term", return_value=_Concept(resolved_models=[])),
        patch("core.routing.routing.generate_investigation_plan", return_value=plan),
        patch("core.routing.routing.validate_plan_against_route", return_value=plan),
    ):
        return route(state)["route"]


def test_current_llm_intent_wins_over_previous_route():
    assert _route(
        "Et pour Lyon ?",
        QuestionIntent.DOCUMENTARY_POLICY,
        last_route=QueryRoute.DONNEES_ERP.value,
    ) == QueryRoute.DOCUMENTAIRE.value


def test_current_system_intent_wins_over_previous_documentation_route():
    assert _route(
        "Qui peut approuver une commande ?",
        QuestionIntent.GOVERNANCE_SECURITY,
        last_route=QueryRoute.DOCUMENTAIRE.value,
    ) == QueryRoute.CODE_INTELLIGENCE.value
