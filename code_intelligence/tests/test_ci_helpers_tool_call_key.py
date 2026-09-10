"""
code_intelligence/tests/test_ci_helpers_tool_call_key.py

Unit tests for code_intelligence.ci_helpers._tool_call_key() -- the single
source of truth for the seen_calls dedup key, shared between the
deterministic pre-dispatch blocks and the LLM-driven ReAct tool calls in
ci_agent_node.py (todo/contexte.txt section 342).

Root cause fixed by this function: before section 342, only the
deterministic pre-dispatch blocks fed seen_calls -- nothing stopped the
ReAct loop (the branch where the LLM picks its own tool_call) from
re-executing a composite tool already pre-dispatched for the same target,
because that branch never consulted seen_calls at all. A system-prompt
instruction ("Do not call it again") asked the LLM not to, but a small
synthesis LLM does not reliably comply (same class of problem as section
250-251 for evaluate_record_rules). _tool_call_key() is the pure function
both call sites now share so they can never disagree on what counts as
"the same call".

Tested here as a pure function (no LLM/graph/tool mocking), matching this
project's convention for extracted pure helpers -- see
tests/test_h1b_ii_rehydrate_ci_node.py for the same pattern applied to
_rehydrate_sticky_concept. The full ReAct loop in
CodeIntelligenceAgentRunner.run() is deliberately NOT exercised here: it
would require mocking the LLM, the knowledge graph, and every composite
tool to reach the dedup branch, which tests far more than the dedup logic
itself. Instead, TestSeenCallsIntegrationPattern below replicates the
exact seen_calls-as-a-set usage pattern from ci_agent_node.py (pre-dispatch
adds a key, ReAct loop checks membership before executing) purely with
_tool_call_key()'s own return values, which is what actually needs to stay
correct for the section 342 fix to hold.
"""

from code_intelligence.agent.ci_agent_node.context.prompt_and_heuristics import (
    _tool_call_key,
    _MODEL_KEYED_TOOLS,
)


# ── Model-keyed composite tools (analyze_security_locks, analyze_server_actions,
#    who_has_access_to, evaluate_record_rules) -- key is (tool_name, model_name) ──

class TestModelKeyedTools:
    def test_same_tool_same_model_produces_equal_keys(self):
        """The exact case the fix targets: a pre-dispatch call and a later
        LLM-requested call for the same tool+model must produce keys equal
        enough to collide in a set."""
        key_predispatch = _tool_call_key("analyze_security_locks", {"model_name": "account.move"})
        key_react_retry = _tool_call_key("analyze_security_locks", {"model_name": "account.move"})
        assert key_predispatch == key_react_retry
        assert key_predispatch is not None

    def test_same_tool_different_model_produces_different_keys(self):
        key_a = _tool_call_key("who_has_access_to", {"model_name": "account.move"})
        key_b = _tool_call_key("who_has_access_to", {"model_name": "hr.leave"})
        assert key_a != key_b

    def test_different_tool_same_model_not_deduped_against_each_other(self):
        """Two distinct composite tools targeting the same model are
        legitimately different calls -- dedup must be per-tool, not just
        per-model."""
        key_locks = _tool_call_key("analyze_security_locks", {"model_name": "account.move"})
        key_acl = _tool_call_key("who_has_access_to", {"model_name": "account.move"})
        assert key_locks != key_acl

    def test_missing_model_name_returns_none(self):
        assert _tool_call_key("analyze_security_locks", {}) is None
        assert _tool_call_key("evaluate_record_rules", {"permission": "read"}) is None

    def test_empty_string_model_name_treated_as_missing(self):
        """tool_args.get('model_name') on an empty string is falsy -- must
        behave like the key entirely absent, not like a real (tool, '') key."""
        assert _tool_call_key("who_has_access_to", {"model_name": ""}) is None

    def test_all_model_keyed_tools_covered(self):
        """Locks in the exact tool set the dedup scheme applies to --
        a regression here (e.g. a composite tool added without being
        added to _MODEL_KEYED_TOOLS) would silently stop being deduped."""
        assert _MODEL_KEYED_TOOLS == frozenset({
            "analyze_security_locks",
            "analyze_server_actions",
            "who_has_access_to",
            "evaluate_record_rules",
            "describe_workflow",
            "trace_full_inheritance",
            "list_involved_modules",
            "analyze_data_constraints",
        })
        for tool_name in _MODEL_KEYED_TOOLS:
            key = _tool_call_key(tool_name, {"model_name": "account.move"})
            assert key == (tool_name, "account.move")


# ── analyze_method_override_chain -- key is (tool_name, model_name, method_name) ──

class TestMethodOverrideChainTool:
    def test_same_model_same_method_produces_equal_keys(self):
        key_a = _tool_call_key(
            "analyze_method_override_chain",
            {"model_name": "account.move", "method_name": "action_post"},
        )
        key_b = _tool_call_key(
            "analyze_method_override_chain",
            {"model_name": "account.move", "method_name": "action_post"},
        )
        assert key_a == key_b == ("analyze_method_override_chain", "account.move", "action_post")

    def test_same_model_different_method_not_deduped(self):
        """A model can have several methods overridden along the approval
        chain -- these are distinct investigations, must not collide."""
        key_post = _tool_call_key(
            "analyze_method_override_chain",
            {"model_name": "account.move", "method_name": "action_post"},
        )
        key_approve = _tool_call_key(
            "analyze_method_override_chain",
            {"model_name": "account.move", "method_name": "action_approve"},
        )
        assert key_post != key_approve

    def test_missing_method_name_returns_none(self):
        assert _tool_call_key(
            "analyze_method_override_chain", {"model_name": "account.move"}
        ) is None

    def test_missing_model_name_returns_none(self):
        assert _tool_call_key(
            "analyze_method_override_chain", {"method_name": "action_post"}
        ) is None

    def test_missing_both_returns_none(self):
        assert _tool_call_key("analyze_method_override_chain", {}) is None


# ── Tools outside the dedup scheme -- always None, dedup never applies ──

class TestOutOfScopeTools:
    def test_read_source_code_never_deduped(self):
        """read_source_code and similar non-composite tools are explicitly
        out of scope per the docstring -- always None, regardless of args,
        so callers never accidentally start deduping a tool the fix was
        never meant to cover."""
        assert _tool_call_key("read_source_code", {"model_name": "account.move"}) is None
        assert _tool_call_key("read_source_code", {"file_path": "x.py"}) is None

    def test_button_execution_path_never_deduped(self):
        assert _tool_call_key(
            "button_execution_path", {"model_name": "account.move", "method_name": "action_post"}
        ) is None

    def test_unknown_tool_name_never_deduped(self):
        assert _tool_call_key("some_future_tool", {"model_name": "account.move"}) is None

    def test_empty_args_dict_returns_none(self):
        assert _tool_call_key("analyze_security_locks", {}) is None


# ── Return type contract: must be hashable (usable in the seen_calls set) ──

class TestReturnTypeContract:
    def test_valid_key_is_a_hashable_tuple(self):
        key = _tool_call_key("analyze_security_locks", {"model_name": "account.move"})
        assert isinstance(key, tuple)
        hash(key)  # must not raise

    def test_none_is_the_explicit_not_dedupable_sentinel(self):
        """Callers in ci_agent_node.py check `if _dup_call_key is not None`
        before consulting seen_calls -- None must never be confused with a
        real key (e.g. a real key must never itself evaluate to None)."""
        assert _tool_call_key("read_source_code", {}) is None


# ── Replicates the exact seen_calls set usage pattern from ci_agent_node.py ──

class TestSeenCallsIntegrationPattern:
    """Mirrors, without any LLM/graph/tool mocking, the two call sites in
    CodeIntelligenceAgentRunner.run() that must agree on seen_calls:
    (1) a deterministic pre-dispatch block adds a key after executing a
    tool for a target model; (2) the ReAct loop, when the LLM proposes a
    tool_call, computes the same key and skips execution if already
    present. This is the actual contract the section 342 fix depends on --
    exercised here purely at the seen_calls/_tool_call_key level, which is
    what needs to stay correct, without needing to drive the full run()
    method end to end."""

    def test_predispatch_then_react_retry_is_detected_as_duplicate(self):
        seen_calls: set = set()

        # Pre-dispatch step (hop #0): analyze_security_locks for account.move.
        predispatch_key = _tool_call_key("analyze_security_locks", {"model_name": "account.move"})
        assert predispatch_key is not None
        seen_calls.add(predispatch_key)

        # ReAct loop (hop #2): LLM re-requests the same tool for the same model.
        react_tool_name = "analyze_security_locks"
        react_tool_args = {"model_name": "account.move"}
        dup_key = _tool_call_key(react_tool_name, react_tool_args)

        assert dup_key is not None
        assert dup_key in seen_calls  # this is the exact check that skips re-execution

    def test_predispatch_then_react_different_model_is_not_a_duplicate(self):
        """A legitimate second investigation on a different model must
        still be allowed to execute."""
        seen_calls: set = set()
        seen_calls.add(_tool_call_key("analyze_security_locks", {"model_name": "account.move"}))

        dup_key = _tool_call_key("analyze_security_locks", {"model_name": "hr.expense"})
        assert dup_key not in seen_calls

    def test_react_loop_call_itself_gets_added_for_a_later_iteration_to_catch(self):
        """Section 342 fix also covers the LLM repeating itself WITHIN the
        ReAct loop (not just after a pre-dispatch): the executed key is
        added to seen_calls too, so a third iteration re-requesting the
        same call is caught by the same check."""
        seen_calls: set = set()

        key_iter1 = _tool_call_key("who_has_access_to", {"model_name": "hr.leave"})
        assert key_iter1 not in seen_calls
        seen_calls.add(key_iter1)  # executed at iteration 1, added post-execution

        key_iter2 = _tool_call_key("who_has_access_to", {"model_name": "hr.leave"})
        assert key_iter2 in seen_calls  # iteration 2 must be skipped

    def test_non_dedupable_tool_calls_never_populate_seen_calls_as_none(self):
        """A None key must never be added to seen_calls -- callers already
        guard with `if _dup_call_key is not None`, but this locks the
        invariant that a second unrelated None-keyed call is never
        mistakenly treated as a duplicate of the first."""
        seen_calls: set = set()
        key_first = _tool_call_key("read_source_code", {"file_path": "a.py"})
        if key_first is not None:
            seen_calls.add(key_first)

        key_second = _tool_call_key("read_source_code", {"file_path": "b.py"})
        assert key_second is None
        assert key_second not in seen_calls  # None was never added, so this holds trivially
        assert len(seen_calls) == 0
