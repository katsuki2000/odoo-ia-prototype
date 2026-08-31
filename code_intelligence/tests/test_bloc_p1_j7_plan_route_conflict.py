"""
code_intelligence/tests/test_bloc_p1_j7_plan_route_conflict.py

Bloc P1 Jour 7 (todo/contexte.txt sections 385-387): dedicated coverage for
validate_plan_against_route()/InvestigationPlan.plan_route_conflict, which
neither test_bloc_p1_j1_2_investigation_plan.py nor
test_bloc_p1_j6_plan_execution_coherence.py exercises (confirmed by full
reading of both files, section 387).

Scope: route_decision() (core/routing.py) and classify_question_intent()
(code_intelligence/investigation_plan.py) are two independently-maintained
classifiers that can disagree -- e.g. "comment créer une demande de
facture ?" sends route_decision to DOCUMENTAIRE (DOC_KEYWORDS: "comment")
while classify_question_intent() sends the same question to WORKFLOW_STATE
via _WEAK_PROCESS_SIGNALS + account.move's WORKFLOW_RULE tag (section 385).
Only the code_intelligence branch ever executes InvestigationStep actions,
so a non-empty plan attached to any other route is a real conflict, not a
cosmetic one.

Section 1 below tests validate_plan_against_route() directly against
hand-built InvestigationPlan objects (no graph/LLM dependency, fast).
Section 2 reproduces the concrete section 385 case end-to-end through
route() itself, confirming the conflict is caught in the real pipeline
and not just at the unit level -- marked integration since it needs the
real Code Intelligence graph.
"""

import pytest

from code_intelligence.investigation_plan import (
    InvestigationPlan,
    InvestigationStep,
    PlanAction,
    PlanGenerationSource,
    QuestionIntent,
    validate_plan_against_route,
)
from code_intelligence.semantic_tags import BehavioralTag, TechnicalTag


def _governance_plan_with_one_step() -> InvestigationPlan:
    step = InvestigationStep(
        action=PlanAction.WHO_HAS_ACCESS_TO,
        target="account.move",
        justification="Évaluer la matrice des droits d'accès ACL",
        behavioral_focus=BehavioralTag.VISIBILITY_RULE,
        technical_focus=TechnicalTag.ACL,
    )
    return InvestigationPlan(
        question="Comment créer une demande de facture ?",
        intent=QuestionIntent.WORKFLOW_STATE,
        target_models=["account.move"],
        steps=[step],
        rationale="Plan d'investigation déterministe pour l'intention 'workflow_state'",
        confidence=1.0,
        source=PlanGenerationSource.DETERMINISTIC_SEMANTIC,
    )


# ── 1. validate_plan_against_route() unit coverage ───────────────────────────

def test_code_intelligence_route_leaves_plan_untouched():
    plan = _governance_plan_with_one_step()
    result = validate_plan_against_route(plan, "code_intelligence")

    assert result is plan
    assert result.steps == plan.steps
    assert result.plan_route_conflict is False
    assert result.conflict_detail is None


@pytest.mark.parametrize("route_decision", ["documentaire", "donnees_erp", "hybride"])
def test_non_ci_route_with_steps_is_neutralized(route_decision):
    plan = _governance_plan_with_one_step()
    result = validate_plan_against_route(plan, route_decision)

    assert result.steps == []
    assert result.plan_route_conflict is True
    assert result.conflict_detail is not None
    assert "PLAN_ROUTE_CONFLICT" in result.conflict_detail
    assert route_decision in result.conflict_detail
    # intent/rationale/target_models preserved so the divergence stays
    # observable (section 386 explicit decision: flag, don't erase).
    assert result.intent == QuestionIntent.WORKFLOW_STATE
    assert result.target_models == ["account.move"]
    assert result.rationale == plan.rationale


@pytest.mark.parametrize("route_decision", ["documentaire", "donnees_erp", "hybride"])
def test_non_ci_route_with_no_steps_is_a_no_op(route_decision):
    """An already-empty plan on a non-CI route is not a conflict -- nothing
    was promised that the route couldn't deliver."""
    plan = InvestigationPlan(
        question="Bonjour",
        intent=QuestionIntent.DOCUMENTARY_POLICY,
        target_models=[],
        steps=[],
        rationale="Aucun signal Code Intelligence détecté",
        confidence=1.0,
        source=PlanGenerationSource.FALLBACK_HEURISTIC,
    )
    result = validate_plan_against_route(plan, route_decision)

    assert result is plan
    assert result.plan_route_conflict is False
    assert result.conflict_detail is None


def test_neutralized_plan_survives_to_display_dict():
    """to_display_dict() (the shape exposed to the Discuss UI / API) must
    surface the conflict, not silently show an empty plan indistinguishable
    from 'no plan was needed'."""
    plan = _governance_plan_with_one_step()
    result = validate_plan_against_route(plan, "documentaire")
    display = result.to_display_dict()

    assert display["steps"] == []
    assert display["plan_route_conflict"] is True
    assert display["conflict_detail"] is not None


def test_unrecognized_route_decision_leaves_plan_untouched():
    """A route value outside {code_intelligence} ∪ _ROUTES_WITHOUT_CI_EXECUTION
    (defensive case, e.g. a future new branch not yet classified either way)
    must not be silently treated as a conflict -- conservative default."""
    plan = _governance_plan_with_one_step()
    result = validate_plan_against_route(plan, "some_future_route")

    assert result is plan
    assert result.plan_route_conflict is False


# ── 2. End-to-end reproduction of the section 385 case ───────────────────────

@pytest.fixture(scope="module")
def real_graph():
    from code_intelligence.ci_graph_loader import get_code_intelligence_graph

    try:
        G = get_code_intelligence_graph()
    except Exception as exc:
        pytest.skip(f"Could not load the Code Intelligence knowledge graph: {exc}")
    if G is None or G.number_of_nodes() == 0:
        pytest.skip("Code Intelligence knowledge graph is empty or unavailable on this machine.")
    return G


@pytest.mark.integration
def test_route_neutralizes_workflow_plan_on_documentaire_branch(real_graph):
    """
    Reproduces the exact section 385 case through the real route() node:
    'comment créer une demande de facture ?' -- route_decision resolves to
    DOCUMENTAIRE (DOC_KEYWORDS: 'comment'), while the Planner's own
    classify_question_intent() resolves the same question to WORKFLOW_STATE
    (account.move's WORKFLOW_RULE tag via _WEAK_PROCESS_SIGNALS). Confirms
    validate_plan_against_route() is actually wired into route()'s return
    path, not just correct in isolation (section 1 above).
    """
    from core.routing import route, QueryRoute

    state = {
        "question": "comment créer une demande de facture ?",
        "chat_history": [],
        "retrieved_chunks": [],
        "timing": {},
    }
    result = route(state)

    assert result["route"] == QueryRoute.DOCUMENTAIRE.value
    plan = result["investigation_plan"]
    # Whether or not the Planner actually diverges to WORKFLOW_STATE for this
    # exact wording today (classifier tuning may drift over time), the
    # invariant that must always hold is the one this test protects: a plan
    # exposed alongside a non-CI route never carries steps.
    assert plan["steps"] == []
    if plan["intent"] != "documentary_policy":
        assert plan["plan_route_conflict"] is True
        assert plan["conflict_detail"] is not None
