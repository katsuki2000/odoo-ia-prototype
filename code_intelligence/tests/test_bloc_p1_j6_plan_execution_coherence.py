"""
code_intelligence/tests/test_bloc_p1_j6_plan_execution_coherence.py

Bloc P1 Jour 6 (todo/plan.md, todo/contexte.txt sections 222-225):
Plan/execution coherence test -- does the plan produced by
generate_investigation_plan() actually correspond to what the real
deterministic pre-dispatch in ci_agent_node.py would execute for the
same question?

Scope (deliberate, matches the factorization already done in sections
210-216): only the 6 tool families backed by a shared deterministic gate
between the Planner and the real forced pre-dispatch are checked --
who_has_access_to, evaluate_record_rules, analyze_security_locks,
can_view_amount_v2, analyze_method_override_chain, analyze_server_actions.
These are exactly the GOVERNANCE_SECURITY branch of generate_investigation_plan().
Other intents (WORKFLOW_STATE, CALCULATION_LOGIC, INHERITANCE_STRUCTURE,
AUTOMATION_ACTION-as-sole-intent) have no equivalent forced/shared gate on
the execution side today -- their plan steps are only ever reachable via
the free-form LLM ReAct loop, so there is nothing deterministic to compare
them against without paying for a real LLM call (explicitly out of scope
per the 2026-08-27 decision: pre-dispatch deterministe seul).

DOC-08 (the documentary counter-example) is deliberately excluded here: its
QuestionIntent is DOCUMENTARY_POLICY, and in the real pipeline it never
reaches code_intelligence_agent at all (routed to the documentary branch by
core/routing.py, gated by concept_suggests_code_intelligence_v2 -- already
covered by test_bloc_p1_j1_2_investigation_plan.py). Testing plan/execution
coherence for a question that never executes here would be out of scope.

Criterion (2026-08-27, todo/contexte.txt section 222, explicit user
decision): INCLUSION, not strict equality --
    planned_tools ⊆ executed_tools
The real forced pre-dispatch is a safety net that may legitimately invoke
MORE tools than the plan announced (e.g. structural guards firing
independently of question wording); that is not a coherence failure. The
real defect to catch is the opposite: a step the plan promises that real
dispatch would never fire. A secondary, non-blocking "extra_tools" count is
logged for drift visibility (see rationale in section 222), not asserted on.

Section 226/227 update (todo/contexte.txt): the first real run of this file
failed 3/5 -- 1 genuine plan/execution coherence bug (WHO_HAS_ACCESS_TO
step never checked the lock-governance exclusion that who_has_access_targets()
itself applies, fixed in investigation_plan.py) and 2 resolution failures
("prêts de matériel", "documents deep" only resolve via LLM arbitration,
not static alias/fuzzy alone -- resolve_business_term(..., llm=None) can't
reach them). Per explicit user decision, concept resolution for ALL H4
questions below now goes through a real, bound LLM client (real_llm
fixture, real Groq call) -- matching what the real execution side
(ci_agent_node.py's CodeIntelligenceAgentRunner, llm=llm) does, unlike
route()'s own plan-generation call (llm=None). This is scoped strictly to
the resolution step: the plan/dispatch coherence check itself stays
deterministic-only (_real_dispatch_targets below still never invokes a
tool or the LLM), consistent with the pre-dispatch-only scope decided
earlier the same day. Hence @pytest.mark.integration on the test.
"""

import logging

import pytest

from code_intelligence.business_resolver import resolve_business_term
from code_intelligence.ci_helpers import _question_is_access_related, _extract_amount
from code_intelligence.investigation_plan import (
    PlanAction,
    QuestionIntent,
    generate_investigation_plan,
)

logger = logging.getLogger(__name__)


# ── Real graph fixture ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_graph():
    """
    Loads the real Code Intelligence knowledge graph (cached JSON on disk if
    present, built from the in-repo custom_* corpus otherwise). Skips
    gracefully rather than failing hard if unavailable on this machine --
    consistent with todo/rules.md's scalability/portability rule (no
    machine-specific hard requirement).
    """
    from code_intelligence.ci_graph_loader import get_code_intelligence_graph

    try:
        G = get_code_intelligence_graph()
    except Exception as exc:
        pytest.skip(f"Could not load the Code Intelligence knowledge graph: {exc}")
    if G is None or G.number_of_nodes() == 0:
        pytest.skip("Code Intelligence knowledge graph is empty or unavailable on this machine.")
    return G


@pytest.fixture(scope="module")
def real_llm():
    """
    Real, bound LLM client for genuine ambiguity arbitration in
    resolve_business_term() (section 226/227, todo/contexte.txt): some H4
    questions below only resolve via LLM arbitration, not static alias/fuzzy
    alone. Makes a real Groq call -- costs quota, hence @pytest.mark.integration
    on the test using this fixture (same convention as
    test_j25_26_e2e_purchase_bypass_gate.py). Skips gracefully if the LLM
    client cannot be constructed on this machine (e.g. missing API key),
    consistent with real_graph's own skip discipline above.
    """
    from core.llm_client import get_chat_llm

    try:
        return get_chat_llm(temperature=0.0, max_retries=0, max_tokens=64)
    except Exception as exc:
        pytest.skip(f"Could not initialize a real LLM client: {exc}")


# ── Mirror of ci_agent_node.py's forced deterministic pre-dispatch ───────────

_CHECKED_ACTIONS = {
    PlanAction.WHO_HAS_ACCESS_TO,
    PlanAction.EVALUATE_RECORD_RULES,
    PlanAction.ANALYZE_SECURITY_LOCKS,
    PlanAction.CAN_VIEW_AMOUNT,
    PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN,
    PlanAction.ANALYZE_SERVER_ACTIONS,
}


def _real_dispatch_targets(question: str, concept, G) -> dict:
    """
    Computes exactly which (action, target_model) pairs
    CodeIntelligenceAgentRunner.run()'s forced deterministic pre-dispatch
    would invoke for this question/concept/graph -- by calling the SAME
    functions it calls (forced_dispatch_predicates.py for the 4 factored
    categories, plus the same inline access+amount gate it uses for
    evaluate_record_rules/can_view_amount_v2, which has no dedicated
    predicate function on either side but is identically gated in both
    ci_agent_node.py and generate_investigation_plan()). Never invokes a
    tool or an LLM -- pure predicate evaluation, same as the Planner itself.
    """
    from code_intelligence.forced_dispatch_predicates import (
        security_locks_targets,
        server_actions_targets,
        override_chain_targets,
        who_has_access_targets,
    )

    targets = {
        PlanAction.ANALYZE_SECURITY_LOCKS: set(security_locks_targets(concept, G)),
        PlanAction.ANALYZE_SERVER_ACTIONS: set(server_actions_targets(question, concept, G)),
        PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN: {
            m for m, _method in override_chain_targets(question, concept, G)
        },
        PlanAction.WHO_HAS_ACCESS_TO: set(who_has_access_targets(question, concept, G)),
        PlanAction.EVALUATE_RECORD_RULES: set(),
        PlanAction.CAN_VIEW_AMOUNT: set(),
    }

    if (
        concept is not None
        and getattr(concept, "is_resolved", False)
        and _question_is_access_related(question)
        and _extract_amount(question) is not None
    ):
        resolved = set(concept.resolved_models)
        targets[PlanAction.EVALUATE_RECORD_RULES] = resolved
        targets[PlanAction.CAN_VIEW_AMOUNT] = resolved

    return targets


# ── H4 questions (same 5 as test_bloc_p1_j1_2_investigation_plan.py) ─────────

H4_QUESTIONS = [
    "Qui a le droit d'approuver les avoirs VIP ?",
    "Est-ce qu'une règle de gestion bloque la validation des congés urgents ?",
    "Qui peut valider une demande d'achat de plus de 15000€ ?",
    "Quelles sont les règles de visibilité pour les prêts de matériel ?",
    "Un employé peut-il voir les documents deep sans autorisation ?",
]


@pytest.mark.integration
@pytest.mark.parametrize("question", H4_QUESTIONS)
def test_plan_steps_are_included_in_real_dispatch_targets(real_graph, real_llm, question):
    """
    Core Jour 6 coherence check: every plan step whose action belongs to the
    6 shared-gate tool families must target a model the real deterministic
    pre-dispatch would actually invoke that tool on (inclusion, not
    equality -- see module docstring).

    Resolution uses a real, bound LLM (real_llm fixture, section 226/227) so
    H4 questions that only resolve via arbitration (not static alias/fuzzy
    alone) are covered too -- matching what the real execution side
    (ci_agent_node.py) does, unlike route()'s own llm=None plan-generation
    call. The LLM is only actually invoked by resolve_business_term on
    genuine ambiguity; questions with a clear static/fuzzy match never call
    it (see business_resolver.py's own step order).
    """
    G = real_graph
    concept = resolve_business_term(question, G, llm=real_llm)
    assert concept.is_resolved, f"business_resolver failed to resolve a known H4 question: {question!r}"

    plan = generate_investigation_plan(question, resolved_concept=concept, G=G)
    assert plan.intent == QuestionIntent.GOVERNANCE_SECURITY, (
        f"Expected H4 question to classify as GOVERNANCE_SECURITY, got {plan.intent!r} "
        f"for {question!r} -- the coherence check below only has a real-dispatch "
        f"equivalent for this branch."
    )

    real_targets = _real_dispatch_targets(question, concept, G)

    violations = []
    for step in plan.steps:
        if step.action not in _CHECKED_ACTIONS:
            continue
        executed_set = real_targets.get(step.action, set())
        if step.target not in executed_set:
            violations.append((step.action.value, step.target))

    assert not violations, (
        f"Plan promises step(s) that real deterministic pre-dispatch would never "
        f"execute for {question!r}: {violations}. "
        f"Real dispatch targets computed: "
        f"{ {a.value: sorted(t) for a, t in real_targets.items()} }"
    )

    # Non-blocking drift signal (section 222): tools the real dispatch would
    # fire that the plan never announced. Logged, not asserted -- a growing
    # gap here over time is a symptom of a plan losing explanatory fidelity
    # even while remaining technically coherent (inclusion still holds).
    planned_pairs = {(s.action, s.target) for s in plan.steps if s.action in _CHECKED_ACTIONS}
    executed_pairs = {
        (action, target) for action, target_set in real_targets.items() for target in target_set
    }
    extra = executed_pairs - planned_pairs
    if extra:
        logger.info(
            "Bloc P1 J6 plan-fidelity drift signal for %r: real dispatch would additionally "
            "invoke %s (not announced by the plan; not a coherence failure, informative only).",
            question, sorted((a.value, t) for a, t in extra),
        )
