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
