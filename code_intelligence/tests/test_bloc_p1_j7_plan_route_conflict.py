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

from code_intelligence.agent.investigation import (
    InvestigationPlan,
    InvestigationStep,
    PlanAction,
    PlanGenerationSource,
    QuestionIntent,
    validate_plan_against_route,
)
from code_intelligence.knowledge_rules.ontology.tags import BehavioralTag, TechnicalTag


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
    from code_intelligence.knowledge_rules.graph import get_code_intelligence_graph

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
    Historical reproduction of the exact section 385 case through the real
    route() node: 'comment créer une demande de facture ?' originally sent
    route_decision to DOCUMENTAIRE (DOC_KEYWORDS: 'comment', route()'s own
    keyword cascade at the time) while the Planner's independent
    classify_question_intent() resolved the same question to WORKFLOW_STATE
    (account.move's WORKFLOW_RULE tag via _WEAK_PROCESS_SIGNALS) -- a real
    divergence between two separately-maintained classifiers.

    todo/contexte.txt section 411: Bloc P1 Tranche 2 (section 394+) since
    replaced route()'s own keyword cascade with a SINGLE
    resolve_question_intent() call, and route() now feeds that SAME `intent`
    into generate_investigation_plan(intent=intent) (see route()'s own
    docstring in core/routing.py: "eliminates the plan/route divergence at
    its root instead of only detecting it after the fact"). Route decision
    and plan intent are therefore no longer independently classified via
    route()'s own codepath -- the specific two-classifier divergence this
    test originally reproduced end-to-end can no longer occur THROUGH
    route() for any question, regardless of which classifier (LLM or
    deterministic fallback) resolves the intent. validate_plan_against_route()
    itself is untouched and still fully covered directly, against hand-built
    conflicting plans, in section 1 above (test_non_ci_route_with_steps_is_neutralized
    et al.) -- what changed is only that route()'s own call site can no
    longer feed it a genuine conflict.

    This test is kept, with a forced deterministic classifier (avoids a live
    LLM call and the network flakiness/non-determinism that comes with it,
    todo/contexte.txt section 411) as a standing regression guard for the
    INVARIANT that actually still matters: whatever route() resolves this
    question to, a plan attached to a non-code_intelligence route must never
    carry steps. It no longer asserts the specific historical route value
    (DOCUMENTAIRE) -- that assertion depended on a two-classifier divergence
    which the Tranche 2 unification deliberately removed at the source, not
    on a property this test should keep re-litigating.
    """
    from unittest.mock import patch
    from core.routing import route, QueryRoute

    with patch("code_intelligence.agent.investigation.classify_question_intent_llm", return_value=None):
        state = {
            "question": "comment créer une demande de facture ?",
            "chat_history": [],
            "retrieved_chunks": [],
            "timing": {},
        }
        result = route(state)

    plan = result["investigation_plan"]
    if result["route"] == QueryRoute.CODE_INTELLIGENCE.value:
        # No conflict possible on this branch -- validate_plan_against_route()
        # is a no-op here (core/investigation_plan.py's own early return).
        assert plan["plan_route_conflict"] is False
    else:
        # The invariant this test protects: a plan exposed alongside a
        # non-CI route never carries steps, whether that plan was already
        # empty at generation (DOCUMENTARY_POLICY/ERP_DATA_QUERY's own
        # dedicated branch in generate_investigation_plan()) or neutralized
        # after the fact by validate_plan_against_route().
        assert plan["steps"] == []
        if plan["intent"] != "documentary_policy":
            assert plan["plan_route_conflict"] is True
            assert plan["conflict_detail"] is not None
