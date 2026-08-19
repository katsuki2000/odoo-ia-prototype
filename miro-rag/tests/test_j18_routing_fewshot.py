# -*- coding: utf-8 -*-
"""
J18-J19: Test suite for the routing function against the few-shot adversarial
examples at branch boundaries. Validates that the conflict resolution policy
(CODE_INTELLIGENCE > DONNEES_ERP > HYBRIDE > DOCUMENTAIRE) is correctly
implemented by the keyword-based router.

These tests run the route() function in isolation (no LLM, no retrieval)
to verify deterministic keyword matching. Each test case corresponds to
one of the 16 few-shot examples in few_shot_routing_examples.py.
"""
import pytest
from rag.graph import (
    ROUTING_CONFLICT_PRIORITY,
    _force_dynamic_uncertainty_answer,
    route,
)
from tests.few_shot_routing_examples import (
    CONFLICT_RESOLUTION_POLICY,
    FEW_SHOT_ROUTING_EXAMPLES,
)


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
    """Bloc 6 requires a documented conflict policy, not only branch selection."""
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


# H1 prototype (2026-08-19, contexte.txt section 60/61 finding F2):
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
        steer route_decision in this first step."""
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
