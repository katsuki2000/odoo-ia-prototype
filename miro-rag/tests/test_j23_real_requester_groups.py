# -*- coding: utf-8 -*-
"""
Bloc 7 (J23-24): tests for the real-auth fix removing the "requester rights"
mock identified when starting the gating work.

Before this fix:
  - ERP/XML-RPC calls silently ran with the admin credential regardless of
    who actually asked (no real per-user Odoo API key was ever produced or
    forwarded).
  - evaluer_regles_enregistrement's user_groups_json was whatever the LLM
    guessed from free text, even though Odoo already sends the demandeur's
    real groups in the JWT -- they were just dropped by the FastAPI layer.

These tests lock in _override_user_groups_arg(), the single choke point
that now forces the real requester groups into that tool call.
"""
import json

from rag.graph import _override_user_groups_arg


def test_overrides_llm_guessed_groups_with_real_ones():
    """The LLM's own user_groups_json must never survive for this tool."""
    state = {"user_groups": [42, 7]}
    tool_args = {"model_name": "account.move", "droit": "read", "user_groups_json": "[\"regional\"]"}

    result = _override_user_groups_arg("evaluer_regles_enregistrement", tool_args, state)

    assert json.loads(result["user_groups_json"]) == [42, 7]


def test_fills_in_real_groups_when_llm_omitted_the_arg():
    """Even if the LLM doesn't supply user_groups_json at all, the real groups must be injected."""
    state = {"user_groups": [3]}
    tool_args = {"model_name": "account.move", "droit": "read"}

    result = _override_user_groups_arg("evaluer_regles_enregistrement", tool_args, state)

    assert json.loads(result["user_groups_json"]) == [3]


def test_empty_requester_groups_yields_empty_list_not_admin_bypass():
    """A requester with no groups must evaluate as genuinely group-less, never fall back to something permissive."""
    state = {"user_groups": []}
    tool_args = {"model_name": "account.move", "user_groups_json": "[\"national\"]"}

    result = _override_user_groups_arg("evaluer_regles_enregistrement", tool_args, state)

    assert json.loads(result["user_groups_json"]) == []


def test_other_tools_are_never_touched():
    """The override is scoped to evaluer_regles_enregistrement only -- e.g. qui_a_acces_a is untouched."""
    state = {"user_groups": [42]}
    tool_args = {"model_name": "account.move", "droit": "all"}

    result = _override_user_groups_arg("qui_a_acces_a", tool_args, state)

    assert "user_groups_json" not in result
    assert result == {"model_name": "account.move", "droit": "all"}


def test_missing_user_groups_in_state_defaults_to_empty_not_a_crash():
    """A state dict without 'user_groups' at all (e.g. a stale caller) must not raise."""
    state = {}
    tool_args = {"model_name": "account.move"}

    result = _override_user_groups_arg("evaluer_regles_enregistrement", tool_args, state)

    assert json.loads(result["user_groups_json"]) == []
