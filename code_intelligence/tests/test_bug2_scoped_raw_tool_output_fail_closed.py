"""
code_intelligence/tests/test_bug2_scoped_raw_tool_output_fail_closed.py

Bug 2 (todo/contexte.txt sections 490-492): regression tests for the
fail-closed fix to code_intelligence.ci_helpers._scoped_raw_tool_output().

Root cause: resolve_technical_name / explain_decision_path / read_source_code
never carry a model_name (no such parameter in ci_agent_tools.py), so their
observation was pushed into tool_observation_models as "" -- and the
previous filter (`if not model or model in target_set`) treated that missing
attribution as "applies to every model", letting the observation leak into
the scoped context of any question regardless of the model actually being
investigated. Fixed filter: `if model and model in target_set` -- a falsy
model is now EXCLUDED whenever target_models is non-empty.

Tested here as a pure function (no LLM/graph/tool mocking), matching this
project's convention for extracted pure helpers (see
test_ci_helpers_tool_call_key.py).
"""

from code_intelligence.agent.ci_agent_node.guards.access_guards import _scoped_raw_tool_output


def test_observation_for_target_model_is_kept():
    output = _scoped_raw_tool_output(
        ["obs account.move"], ["account.move"], ["account.move"],
    )
    assert output == "obs account.move"


def test_observation_for_a_different_model_is_dropped():
    output = _scoped_raw_tool_output(
        ["obs sale.order"], ["sale.order"], ["account.move"],
    )
    assert output == ""


def test_observation_with_empty_string_model_is_dropped_when_target_set():
    """Core of the fix: an empty-string model_name (resolve_technical_name /
    explain_decision_path / read_source_code) is EXCLUDED once a target
    model is set -- absence of attribution is never an implicit
    'applies everywhere' authorization."""
    output = _scoped_raw_tool_output(
        ["obs no model"], [""], ["account.move"],
    )
    assert output == ""


def test_observation_with_none_model_is_dropped_when_target_set():
    output = _scoped_raw_tool_output(
        ["obs none model"], [None], ["account.move"],
    )
    assert output == ""


def test_mixed_observations_only_target_model_kept():
    output = _scoped_raw_tool_output(
        ["obs account.move", "obs sale.order", "obs no model"],
        ["account.move", "sale.order", ""],
        ["account.move"],
    )
    assert output == "obs account.move"


def test_no_target_models_at_all_returns_everything_unscoped():
    """Unchanged pre-existing behavior (early return, section 490): when
    target_models itself is empty/None, nothing is scoped -- this is a
    distinct case from 'a target is set but this observation lacks a
    model_name', and the fail-closed fix must not touch it."""
    output = _scoped_raw_tool_output(
        ["obs a", "obs b"], ["account.move", ""], [],
    )
    assert output == "obs a\n\nobs b"
