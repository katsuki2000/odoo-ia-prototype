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
from rag.graph import route
from tests.few_shot_routing_examples import FEW_SHOT_ROUTING_EXAMPLES


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
