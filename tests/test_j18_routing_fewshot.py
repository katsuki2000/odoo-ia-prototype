"""Tests for the simplified two-source router."""

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


def _route(question, intent, source_mode=None):
    state = {
        "question": question,
        "source_mode": source_mode,
        "timing": {},
        "chat_history": [],
    }
    plan = SimpleNamespace(to_display_dict=lambda: {})
    with (
        patch("core.routing.routing.resolve_question_intent", return_value=SimpleNamespace(intent=intent, source="llm")),
        patch("code_intelligence.graph.loader.get_code_intelligence_graph"),
        patch("code_intelligence.agent.resolver.resolve_business_term", return_value=_Concept(resolved_models=[])),
        patch("core.routing.routing.generate_investigation_plan", return_value=plan),
        patch("core.routing.routing.validate_plan_against_route", return_value=plan),
    ):
        return route(state)["route"]


def test_llm_can_select_documentation_when_user_did_not_choose():
    assert _route("Quelle est la procédure interne ?", QuestionIntent.DOCUMENTARY_POLICY) == QueryRoute.DOCUMENTAIRE.value


def test_llm_can_select_system_data():
    assert _route("Combien de ventes ?", QuestionIntent.ERP_DATA_QUERY) == QueryRoute.DONNEES_ERP.value


def test_llm_can_select_system_code_intelligence():
    assert _route("Qui peut approuver une commande ?", QuestionIntent.GOVERNANCE_SECURITY) == QueryRoute.CODE_INTELLIGENCE.value


def test_explicit_documentation_choice_skips_intent_classification_and_system_resolution():
    with (
        patch("core.routing.routing.resolve_question_intent") as classify,
        patch("code_intelligence.agent.resolver.resolve_business_term") as resolve,
    ):
        result = route({
            "question": "Explique les règles",
            "source_mode": "documentation",
            "timing": {},
        })
    assert result["route"] == QueryRoute.DOCUMENTAIRE.value
    assert result["investigation_plan"] is None
    classify.assert_not_called()
    resolve.assert_not_called()


def test_explicit_system_choice_overrides_documentary_intent():
    assert _route(
        "Explique les règles de codage",
        QuestionIntent.DOCUMENTARY_POLICY,
        source_mode="systeme",
    ) == QueryRoute.CODE_INTELLIGENCE.value
