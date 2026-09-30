"""
Section 1028: a satisfied display condition must never be presented as a cause.

PUR-Q4 asks why 'Approve Order' is hidden for a simple user although the order
is in state 'to approve'. The `invisible` expression is satisfied by that state,
so the only blocking cause is the group restriction. The deterministic fact
below gives the synthesis step that decomposition instead of leaving it to
guess a second cause.
"""

import networkx as nx
import pytest

from code_intelligence.agent.prompts import build_synthesis_prompt
from code_intelligence.rules.button_path import (
    DISPLAY_CAUSES_MARKER,
    button_execution_path,
    parse_visibility_rule,
)

MODEL = "purchase.order"
MANAGER_GROUP = "purchase.group_purchase_manager"
QUESTION_WITH_STATE = (
    "Pourquoi le bouton 'Approve Order' n'est-il pas visible pour un utilisateur simple "
    "meme quand la commande est au statut 'to approve' ?"
)
QUESTION_WITHOUT_STATE = "Pourquoi le bouton 'Approve Order' n'est-il pas visible pour un utilisateur simple ?"


def _graph_with_button(invisible: str) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node(f"model:{MODEL}", node_type="Model", name=MODEL)
    G.add_edge(
        f"model:{MODEL}",
        "button:approve_order",
        edge_type="HAS_BUTTON",
        method_name="button_approve",
        label_bouton="Approve Order",
        groupe_requis=[MANAGER_GROUP],
        invisible=invisible,
    )
    return G


def _run(invisible: str, question: str, user_groups):
    return button_execution_path(
        _graph_with_button(invisible), "Approve Order", MODEL,
        user_groups=user_groups, premise_text=question,
    )


def test_state_named_in_question_is_reported_satisfied_and_group_is_the_only_cause():
    result = _run("state != 'to approve'", QUESTION_WITH_STATE, [])
    assert result.satisfied_conditions == ["state == 'to approve'"]
    assert result.blocking_causes == ["le demandeur n'appartient à aucun des groupes requis"]
    assert DISPLAY_CAUSES_MARKER in result.summary_text
    assert "n'est pas une anomalie" in result.summary_text


def test_no_fact_when_the_question_does_not_name_the_visible_state():
    result = _run("state != 'to approve'", QUESTION_WITHOUT_STATE, [])
    assert result.satisfied_conditions == []
    assert DISPLAY_CAUSES_MARKER not in result.summary_text


def test_no_fact_when_the_requester_belongs_to_the_required_group():
    result = _run("state != 'to approve'", QUESTION_WITH_STATE, [MANAGER_GROUP])
    assert result.blocking_causes == []
    assert DISPLAY_CAUSES_MARKER not in result.summary_text


def test_compound_expression_is_never_guessed():
    result = _run("state != 'to approve' or not is_shipped", QUESTION_WITH_STATE, [])
    assert result.satisfied_conditions == []
    assert DISPLAY_CAUSES_MARKER not in result.summary_text
    assert "visible quand" not in result.summary_text


def test_not_in_expression_lists_only_the_state_named_in_the_question():
    result = _run("state not in ('to approve', 'sent')", QUESTION_WITH_STATE, [])
    assert result.satisfied_conditions == ["state == 'to approve'"]
    assert "visible quand state in ('to approve', 'sent')" in result.summary_text


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("state != 'draft'", ("state", ["draft"])),
        ('state != "draft"', ("state", ["draft"])),
        ("state not in ('a', 'b')", ("state", ["a", "b"])),
        ("state not in ['a']", ("state", ["a"])),
        ("state == 'draft'", None),
        ("state != 'a' and x", None),
        ("", None),
    ],
)
def test_parse_visibility_rule(expression, expected):
    assert parse_visibility_rule(expression) == expected


def test_synthesis_prompt_carries_the_rule_only_when_the_fact_is_present():
    with_fact = build_synthesis_prompt(QUESTION_WITH_STATE, [f"Button. {DISPLAY_CAUSES_MARKER} x"])
    without_fact = build_synthesis_prompt(QUESTION_WITH_STATE, ["Button. nothing special"])
    assert "ONLY the blocking cause" in with_fact
    assert "ONLY the blocking cause" not in without_fact
