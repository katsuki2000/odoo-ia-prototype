"""
tests/test_bug2_backfill_scoped_output_wiring.py

Bug 2 non-regression (todo/contexte.txt section 492): static wiring check
that every backfill/correction call downstream of the fail-closed scoping
fix in CodeIntelligenceAgentRunner.run() is fed exclusively through
scoped_tool_output -- never through the unscoped raw_tool_output variable
(the tool_observations join computed BEFORE scoping). A call site silently
switched back to raw_tool_output would reintroduce every falsy-model
observation (resolve_technical_name / explain_decision_path /
read_source_code) that _scoped_raw_tool_output() now deliberately drops --
exactly the kind of "different mechanism" reintroduction the fix must
guard against, and one no dynamic test can catch cheaply (it would require
mocking the LLM, the graph, and every CI tool to reach this code path).

raw_tool_output itself is legitimately used earlier in run() for the
out-of-scope / dynamic-uncertainty checks and, deliberately, as the ground
truth passed to sourcing_guard.verify_citations() -- that call is a
citation-verification concern (checking what the LLM cited against
everything the tools actually produced), not a content-backfill channel,
and is explicitly excluded from this check.
"""

import inspect
import re

from code_intelligence.ci_agent_node import CodeIntelligenceAgentRunner

_BACKFILL_AND_CORRECTION_FUNCS = [
    "_backfill_missing_required_groups",
    "_backfill_missing_security_lock_amount",
    "_backfill_missing_override_modules",
    "_correct_override_cascade_contradictions",
    "_backfill_missing_override_chain_amount",
    "_backfill_missing_trigger_condition_literals",
    "_backfill_missing_hardcoded_id_literals",
    "_backfill_missing_unguarded_super",
    "_backfill_link_guard_clarifications",
    "_flag_ungrounded_group_xmlids",
    "_strip_core_only_group_mentions",
    "_backfill_missing_can_view_amount_fact",
    "_correct_security_lock_threshold_contradictions",
]


def test_all_backfill_and_correction_calls_use_scoped_tool_output():
    source = inspect.getsource(CodeIntelligenceAgentRunner.run)
    _, marker, post_scoping = source.partition(
        "scoped_tool_output = _scoped_raw_tool_output("
    )
    assert marker, "scoping call not found in CodeIntelligenceAgentRunner.run source -- test is stale"

    for func_name in _BACKFILL_AND_CORRECTION_FUNCS:
        calls = list(re.finditer(re.escape(func_name) + r"\(([^)]*)\)", post_scoping))
        assert calls, f"{func_name} is not called after the scoping point -- test is stale"
        for m in calls:
            call_args = m.group(1)
            assert "raw_tool_output" not in call_args, (
                f"{func_name} call uses raw_tool_output instead of "
                f"scoped_tool_output -- this reintroduces observations the "
                f"fail-closed fix (section 492) is meant to drop: {call_args!r}"
            )
