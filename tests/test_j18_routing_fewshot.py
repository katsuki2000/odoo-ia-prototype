# -*- coding: utf-8 -*-
"""
Test suite for the routing function against the few-shot adversarial
examples at branch boundaries. Validates that the conflict resolution policy
(CODE_INTELLIGENCE > DONNEES_ERP > HYBRIDE > DOCUMENTAIRE) is correctly
implemented by the keyword-based router.

These tests run route() with the bounded LLM intent classifier forced
unavailable (see _force_deterministic_intent_classifier below), so what
actually gets exercised is the deterministic classify_question_intent()
fallback -- no live network call, no retrieval. Each test case corresponds
to one of the few-shot examples in few_shot_routing_examples.py, which is
a golden-master SPEC of the intended conflict-resolution policy, not a
recording of whatever the LLM classifier currently happens to produce.

todo/contexte.txt section 411: Bloc P1 Tranche 2 (section 394+) wired
route() through resolve_question_intent(), which tries the real Groq LLM
classifier FIRST and only falls back to classify_question_intent() on
failure -- without this forced fallback, every route() call here silently
started making live, non-deterministic, ~3.7s-per-call network requests,
and 5 of these 67 cases diverged from the golden-master spec (confirmed
section 404/411: the LLM classifies them into a different QuestionIntent
than the hand-tuned keyword cascade). That LLM-vs-spec divergence is a
separate, already-tracked, still-open concern (section 404, options A-D
never mandated) and is deliberately NOT re-litigated by this file --
forcing the fallback here restores this module's original, documented
purpose (a deterministic spec of the keyword-based policy) instead of
silently rewriting the spec to match today's LLM output.
"""
from unittest.mock import patch

import pytest
from core.graph.graph import (
    ROUTING_CONFLICT_PRIORITY,
    _force_dynamic_uncertainty_answer,
    route,
)
from tests.few_shot_routing_examples import (
    CONFLICT_RESOLUTION_POLICY,
    FEW_SHOT_ROUTING_EXAMPLES,
)


@pytest.fixture(autouse=True)
def _force_deterministic_intent_classifier():
    """
    Forces every route() call in this module through the deterministic
    classify_question_intent() fallback by making the bounded LLM
    classifier report unavailable (returns None) -- the same signal
    classify_question_intent_llm() itself returns on any real failure (see
    its own docstring in code_intelligence/investigation_plan.py). This is
    a deliberate, documented mock restoring this module's original scope
    (module docstring above), not a silent bypass of a bug: the LLM
    classifier's real behavior on these same cases is covered separately
    (todo/contexte.txt section 404/411).
    """
    with patch("code_intelligence.agent.investigation_planner.classify_question_intent_llm", return_value=None):
        yield


def _route_question(question: str) -> str:
    """Run the route() function on a question with empty chunks and return the route decision."""
    state = {
        "question": question,
        "retrieved_chunks": [],
        "chat_history": [],
        "timing": {},
    }
    result = route(state)
    return result["route"]


@pytest.mark.parametrize(
    "example",
    FEW_SHOT_ROUTING_EXAMPLES,
    ids=[ex["question"][:60] for ex in FEW_SHOT_ROUTING_EXAMPLES],
)
def test_few_shot_routing(example):
    """Each few-shot example must route to its expected branch."""
    actual = _route_question(example["question"])
    expected = example["expected_route"]
    assert actual == expected, (
        f"\nQuestion: {example['question']}\n"
        f"Expected: {expected}\n"
        f"Actual:   {actual}\n"
        f"Rationale: {example['rationale']}\n"
        f"Conflict: {example['conflict_notes']}"
    )


def test_conflict_policy_is_explicit_and_ordered():
    """ requires a documented conflict policy, not only branch selection."""
    assert ROUTING_CONFLICT_PRIORITY == (
        "code_intelligence",
        "donnees_erp",
        "hybride",
        "documentaire",
    )
    assert "Code > Wiki" in CONFLICT_RESOLUTION_POLICY
    assert "Données ERP > Code" in CONFLICT_RESOLUTION_POLICY
    assert "HYBRIDE uniquement si deux sous-questions distinctes" in CONFLICT_RESOLUTION_POLICY


@pytest.mark.parametrize(
    "example",
    FEW_SHOT_ROUTING_EXAMPLES,
    ids=[ex["question"][:60] for ex in FEW_SHOT_ROUTING_EXAMPLES],
)
def test_each_few_shot_case_documents_decision(example):
    """Each ambiguous-boundary case must explain which branch wins and why."""
    assert example["expected_route"] in ROUTING_CONFLICT_PRIORITY
    assert example["rationale"].strip()
    assert example["conflict_notes"].strip()


def test_hybrid_detects_doc_anchor_not_only_doc_keyword():
    """
    Regression for a J20-J21 review finding: is_hybrid must fire on DOC_ANCHORS
    ("où est documenté", "dans le wiki", "wiki interne", "selon la politique interne"),
    not only on DOC_KEYWORDS. Before the fix, anchors absent from DOC_KEYWORDS caused
    a doc-anchor + quantitative question to silently route to DOCUMENTAIRE instead of
    HYBRIDE, because is_hybrid never became True and the has_doc_anchor branch fell
    back to its else clause.
    """
    for anchor in ("où est documenté", "dans le wiki", "wiki interne", "selon la politique interne"):
        question = f"{anchor}, combien de tickets sont encore en cours ?"
        assert _route_question(question) == "hybride", (
            f"Doc anchor '{anchor}' + quantitative term should route to HYBRIDE, not fall "
            f"through to DOCUMENTAIRE."
        )


def test_dynamic_dispatch_uncertainty_cannot_be_synthesized_as_certain():
    raw = (
        "Analyse des verrous Python "
        "([reimbursement.py:L1-L31](file:///tmp/reimbursement.py#L1-L31)) "
        "[Confiance: LOW]:\n"
        "  - Incertitude dynamique (getattr): revue manuelle recommandée"
    )
    answer = _force_dynamic_uncertainty_answer(
        "Qui peut valider une demande de remboursement de frais ?",
        raw,
    )
    assert answer is not None
    assert "Je ne peux pas classifier avec certitude" in answer
    assert "getattr" in answer
    assert "file:///tmp/reimbursement.py#L1-L31" in answer
    assert "aucune restriction" not in answer.lower()


# H1 prototype (2026-08-19,  section 60/61 finding F2):
# business_resolver.py is now invoked once at the top of route(), before
# any keyword classification, deliberately observational-only (see the
# comment block at the top of route() in rag/graph.py for the full
# rationale, including the DOC-08 regression this design was changed to
# avoid). These tests lock in the two properties that matter for this
# first step: (1) the resolved concept is genuinely computed and exposed
# on state, so a later step can build on it without recomputing, and (2)
# every single existing routing decision -- including the one case that
# would have broken had business_resolver been allowed to steer
# route_decision -- is completely unchanged.
class TestH1BusinessResolverExposedBeforeRoute:
    def test_resolved_concept_is_present_on_returned_state(self):
        """Any question at all must come back with a resolved_concept dict
        (never a missing key), regardless of whether resolution succeeded."""
        state = {
            "question": "Comment configurer le module de comptabilité dans Odoo 17 ?",
            "retrieved_chunks": [],
            "chat_history": [],
            "timing": {},
        }
        result = route(state)
        assert "resolved_concept" in result
        assert isinstance(result["resolved_concept"], dict)

    def test_static_alias_question_resolves_but_does_not_change_the_route(self):
        """The exact DOC-08 regression case (tests/benchmark_questions.json):
        'mise à disposition' resolves deterministically via the static alias
        tier to custom.asset.loan, but the question asks about a wiki-
        documented SLA, not governance/code -- the correct route stays
        DOCUMENTAIRE (via the unchanged no-chunks default), proving
        resolution success is exposed on state without being allowed to
        steer route_decision in this first step.

        Relies on _force_deterministic_intent_classifier (module-level
        autouse fixture) to reach classify_question_intent()'s own DOC-08
        guard (step 9 default, todo/contexte.txt section 411): the bounded
        LLM classifier does not receive resolved_concept at all and, left
        unforced, classified this exact wording as CODE_INTELLIGENCE
        instead (section 404/411) -- a separate, already-tracked concern,
        not a regression of the DOC-08 guard this test protects."""
        state = {
            "question": "Quel est le délai de traitement pour une demande de mise à disposition ?",
            "retrieved_chunks": [],
            "chat_history": [],
            "timing": {},
        }
        result = route(state)
        concept = result["resolved_concept"]
        assert concept["is_resolved"] is True
        assert concept["source_step"] == "static_alias"
        assert "custom.asset.loan" in concept["resolved_models"]
        assert result["route"] == "documentaire"

    def test_unresolved_question_still_routes_normally(self):
        """Relies on _force_deterministic_intent_classifier (module-level
        autouse fixture, todo/contexte.txt section 411): the bounded LLM
        classifier, left unforced, classified this exact wording as
        CODE_INTELLIGENCE instead of DOCUMENTAIRE (section 404/411) --
        a separate, already-tracked concern, not a regression of the
        unresolved-concept default this test protects."""
        state = {
            "question": "Quels sont les modules Odoo considérés comme sensibles et qui y a accès ?",
            "retrieved_chunks": [],
            "chat_history": [],
            "timing": {},
        }
        result = route(state)
        assert result["resolved_concept"]["is_resolved"] is False
        assert result["route"] == "documentaire"

    @pytest.mark.parametrize(
        "example",
        FEW_SHOT_ROUTING_EXAMPLES,
        ids=[ex["question"][:60] for ex in FEW_SHOT_ROUTING_EXAMPLES],
    )
    def test_every_few_shot_route_decision_is_unaffected(self, example):
        """Full non-regression sweep: computing resolved_concept up front
        must never change any of the 16 already-locked few-shot routing
        decisions, whether or not business_resolver happens to resolve
        something on that question."""
        actual = _route_question(example["question"])
        assert actual == example["expected_route"]
