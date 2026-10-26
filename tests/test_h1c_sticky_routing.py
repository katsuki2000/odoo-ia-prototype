"""Routing follows the current classifier result; it does not reuse a previous source route."""

from dataclasses import dataclass
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



def test_sticky_concept_is_used_to_build_followup_investigation_plan():
    previous = {
        "user_term": "congés",
        "resolved_models": ["hr.leave"],
        "resolved_modules": ["hr_holidays"],
        "confidence": 0.91,
        "source_step": "static_alias",
        "is_resolved": True,
        "reason": "previous turn",
        "diagnostics": {},
    }
    plan = SimpleNamespace(to_display_dict=lambda: {"target_models": ["hr.leave"]})
    graph = object()

    with (
        patch(
            "core.routing.routing.resolve_question_intent",
            return_value=SimpleNamespace(
                intent=QuestionIntent.GOVERNANCE_SECURITY, source="llm"
            ),
        ),
        patch(
            "code_intelligence.graph.loader.get_code_intelligence_graph",
            return_value=graph,
        ),
        patch(
            "code_intelligence.agent.resolver.resolve_business_term",
            return_value=_Concept(
                user_term="Et pour celle-ci ?",
                resolved_models=[],
                resolved_modules=[],
                is_resolved=False,
            ),
        ),
        patch(
            "core.routing.routing.generate_investigation_plan",
            return_value=plan,
        ) as generate_plan,
        patch(
            "core.routing.routing.validate_plan_against_route",
            return_value=plan,
        ),
    ):
        result = route({
            "question": "Et pour celle-ci ?",
            "timing": {},
            "last_resolved_concept": previous,
            "user_groups": [],
            "language": "fr_FR",
        })

    planned_concept = generate_plan.call_args.kwargs["resolved_concept"]
    assert planned_concept.is_resolved is True
    assert planned_concept.resolved_models == ["hr.leave"]
    assert planned_concept.resolved_modules == ["hr_holidays"]
    assert result["resolved_concept"]["resolved_models"] == ["hr.leave"]
    assert result["resolved_concept_reused"] is True
    assert result["investigation_plan"]["target_models"] == ["hr.leave"]
