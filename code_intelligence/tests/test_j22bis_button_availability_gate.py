"""
code_intelligence/tests/test_j22bis_button_availability_gate.py

 (revision 2026-08-07): real button availability for "comment
faire X ?" questions.

  button_execution_path (deterministic_tools.py) now accepts an optional
  user_groups argument and computes available_to_requester by reusing the
  SAME tolerant group resolver already used by who_has_access_to and
  evaluate_record_rules (resolve_group_identifier) -- never a
  second reimplementation of Odoo's group-matching semantics. When the
  demandeur is not a member of any of the button's required_groups, the
  result must say so explicitly (summary + a dedicated execution step)
  instead of silently walking them through a mechanism they cannot
  actually trigger.

  rag/graph.py's _override_user_groups_arg also applies this same
  real-groups override to button_execution_path's tool_args, exactly
  like it already does for evaluate_record_rules -- whatever
  user_groups_json the LLM proposes is discarded in favor of the real
  requester's resolved groups.

This file was referenced in real  /   as an existing regression lock, but was never actually created
on disk -- confirmed 2026-08-07 via `pytest ... -v` returning "no tests
ran" / "file or directory not found". The underlying code
(deterministic_tools.button_execution_path,
_requester_satisfies_required_groups, rag.graph._override_user_groups_arg)
IS present and wired into ci_agent_tools.py / CI_SYSTEM_PROMPT rule 6 --
only this test file itself was missing. See  for the note on
this gap.
"""

import networkx as nx

from code_intelligence.deterministic.navigation.button_path import button_execution_path


def _build_graph_with_button(
    model_name: str,
    required_groups=None,
    button_group_display_name: str = "",
) -> nx.DiGraph:
    """Synthetic graph with one workflow transition button, mirroring the
    shape used in test_b1_3.py::test_button_execution_path_synthetic."""
    G = nx.DiGraph()
    G.add_node(f"model:{model_name}", node_type="Model", name=model_name)
    G.add_node(
        f"method:{model_name}.action_valider_avoir",
        node_type="Method", name="action_valider_avoir", model=model_name,
    )
    G.add_node(f"state:{model_name}.draft", node_type="WorkflowState", model=model_name, state_value="draft")
    G.add_node(f"state:{model_name}.validated", node_type="WorkflowState", model=model_name, state_value="validated")

    groups_req = required_groups or []
    G.add_edge(
        f"state:{model_name}.draft",
        f"state:{model_name}.validated",
        edge_type="TRANSITIONS_VIA",
        method_name="action_valider_avoir",
        label_bouton="Valider",
        groupe_requis=groups_req,
    )

    # Optional group node with a human-readable display name, needed for
    # the tolerant fuzzy-resolution test below (mirrors
    # deterministic_tools._group_fuzzy_matches_display_name's expectations).
    if groups_req and button_group_display_name:
        G.add_node(f"group:{groups_req[0]}", node_type="Group", name=button_group_display_name)

    return G


def test_button_available_when_demandeur_is_member_of_required_group():
    G = _build_graph_with_button(
        "account.move", required_groups=["account.group_account_manager"],
    )
    res = button_execution_path(
        G, "Valider", "account.move",
        user_groups=["account.group_account_manager"],
    )
    assert res.available_to_requester is True
    assert res.unavailable_reason == ""
    assert "NON DISPONIBLE" not in res.summary_text
    assert any("Disponibilite reelle : OUI" in step for step in res.execution_steps)


def test_button_unavailable_when_demandeur_lacks_required_group():
    G = _build_graph_with_button(
        "account.move", required_groups=["account.group_account_manager"],
    )
    res = button_execution_path(
        G, "Valider", "account.move",
        user_groups=["base.group_user"],
    )
    assert res.available_to_requester is False
    assert "account.group_account_manager" in res.unavailable_reason
    assert "n'est pas disponible" in res.unavailable_reason.lower() or "pas disponible" in res.unavailable_reason.lower()
    assert "NON DISPONIBLE POUR LE DEMANDEUR" in res.summary_text
    assert any("Disponibilite reelle : NON" in step for step in res.execution_steps)


def test_button_with_no_required_groups_is_always_available():
    """A button with no button-level group restriction is open to
    everyone, even a demandeur with zero groups -- same convention as the
    'No button-level group restriction specified' security-requirement
    step already asserted elsewhere."""
    G = _build_graph_with_button("account.move", required_groups=[])
    res = button_execution_path(G, "Valider", "account.move", user_groups=[])
    assert res.available_to_requester is True
    assert res.unavailable_reason == ""


def test_no_user_groups_argument_keeps_prior_behavior_unchanged():
    """Non-regression: when user_groups is not supplied at all (None,
    existing callers' default), available_to_requester must stay None
    (never guessed as True or False) and no step 5 is appended -- matches
    test_b1_3.py::test_button_execution_path_synthetic, which still
    asserts exactly 4 execution_steps for this exact scenario."""
    G = _build_graph_with_button(
        "account.move", required_groups=["account.group_account_manager"],
    )
    res = button_execution_path(G, "Valider", "account.move")
    assert res.available_to_requester is None
    assert res.unavailable_reason == ""
    assert len(res.execution_steps) == 4


def test_tolerant_group_resolution_short_name_matches_required_group():
    """Reuses resolve_group_identifier  rather than a strict exact
    match: a demandeur-supplied short group name (no module prefix) must
    still resolve against a fully-qualified required_groups entry, exactly
    like who_has_access_to and evaluate_record_rules already tolerate."""
    G = _build_graph_with_button(
        "custom.reimbursement.request",
        required_groups=["custom_credit_note_visibility_rules.group_avoir_national"],
    )
    res = button_execution_path(
        G, "Valider", "custom.reimbursement.request",
        user_groups=["group_avoir_national"],  # short name, no module prefix
    )
    assert res.available_to_requester is True


def test_tolerant_group_resolution_fuzzy_display_name_matches_required_group():
    """A demandeur-supplied bare business word (fuzzy-matched against the
    required group's human-readable display name) must also resolve --
    same third fallback step already used by resolve_group_identifier
    elsewhere in the module."""
    G = _build_graph_with_button(
        "custom.reimbursement.request",
        required_groups=["custom_credit_note_visibility_rules.group_avoir_national"],
        button_group_display_name="Avoirs - Visibilite Nationale",
    )
    res = button_execution_path(
        G, "Valider", "custom.reimbursement.request",
        user_groups=["national"],
    )
    assert res.available_to_requester is True


def test_override_user_groups_arg_applies_to_button_execution_path():
    """core.graph._override_user_groups_arg must discard whatever
    user_groups_json the LLM proposed for button_execution_path and
    replace it with the real, resolved demandeur groups -- same treatment
    already locked in for evaluate_record_rules ."""
    from core.graph import _override_user_groups_arg

    llm_guessed_args = {"button_name": "Valider", "model_name": "account.move", "user_groups_json": '["made_up_group"]'}
    real_groups = ["account.group_account_manager"]

    result = _override_user_groups_arg("button_execution_path", llm_guessed_args, real_groups)

    assert result["user_groups_json"] == '["account.group_account_manager"]'
    assert "made_up_group" not in result["user_groups_json"]


def test_override_user_groups_arg_is_noop_for_unrelated_tools():
    from core.graph import _override_user_groups_arg

    args = {"model_name": "account.move"}
    result = _override_user_groups_arg("who_has_access_to", args, ["account.group_account_manager"])
    assert "user_groups_json" not in result
