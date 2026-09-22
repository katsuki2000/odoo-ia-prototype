"""
Section 893/894 (todo/contexte.txt): who_has_access_to was missing its own
entry in PER_TOOL_OBSERVATION_CAPS, and the deterministic pre-dispatch call
site (predispatch_access.py) additionally hardcoded its own 3000-char
literal independently of that dict -- so fixing the dict alone would not
have changed the deterministic dispatch path's actual behavior. Both are
covered here: the dict value itself, and the real call site reading it.
"""

from unittest.mock import MagicMock

# Import through the production entry point first: importing agent.context
# or predispatch_access directly hits a pre-existing circular import
# (agent.context <-> rules.security_evidence), same as section 876 --
# not introduced by this test.
import code_intelligence.agent.loop  # noqa: F401

from code_intelligence.agent.context import (
    PER_TOOL_OBSERVATION_CAPS,
    DEFAULT_OBSERVATION_CAP,
    DispatchContext,
    _truncate_observation_for_budget,
)
from code_intelligence.agent.predispatch_access import dispatch_who_has_access_to


def _make_ctx(question, resolved_models, tool_map, trace_logger=None):
    concept = MagicMock(is_resolved=True, resolved_models=resolved_models)
    return DispatchContext(
        G=MagicMock(), concept=concept, question=question, tool_map=tool_map,
        resolved_user_group_xmlids=[], trace_logger=trace_logger or MagicMock(),
        trace_id="t", hop_cap=6,
    )


def test_who_has_access_to_has_its_own_cap_entry():
    """Section 893/894: absent from the dict meant a silent fallback to
    DEFAULT_OBSERVATION_CAP (2500) wherever the caller consults the dict
    (the free-ReAct tool-call path in loop.py)."""
    assert "who_has_access_to" in PER_TOOL_OBSERVATION_CAPS
    assert PER_TOOL_OBSERVATION_CAPS["who_has_access_to"] == 11000


def test_cap_gives_headroom_over_measured_worst_case():
    """Measured directly (section 893/894, execution directe, vrai graphe)
    across the 12 N1-bank models x {read,write,all}: maintenance.request is
    the worst case at 9137 chars, stock.move.line close behind at 8837,
    everything else <=2664. 11000 must clear the worst case with margin."""
    worst_case_measured = 9137
    cap = PER_TOOL_OBSERVATION_CAPS["who_has_access_to"]
    assert cap > worst_case_measured
    assert cap / worst_case_measured > 1.16  # >=16% headroom, as documented


def test_default_cap_would_have_truncated_the_worst_case():
    """Negative control: without a dedicated entry, the 2500-char default
    cuts off well before either worst case -- confirms the gap was real,
    not a theoretical concern."""
    assert DEFAULT_OBSERVATION_CAP < 9137
    assert DEFAULT_OBSERVATION_CAP < 8837


def test_dispatch_who_has_access_to_uses_the_dict_value_not_a_hardcoded_literal():
    """Section 894: predispatch_access.py's deterministic dispatcher used to
    hardcode 3000 directly (independent of PER_TOOL_OBSERVATION_CAPS) -- a
    real gap for maintenance.request (9137, would silently lose everything
    past the WRITE section) even after the dict itself is fixed, since this
    call site never reads it. Confirmed by observing the actual truncation
    limit passed to _truncate_observation_for_budget: a fake tool whose raw
    observation is exactly at the boundary between the OLD hardcoded value
    and the NEW dict value proves which one is actually in effect."""
    raw_9500_chars = "X" * 9500  # between the old hardcoded 3000 and the dict's 11000
    fake_tool = MagicMock()
    fake_tool.invoke.return_value = raw_9500_chars

    ctx = _make_ctx(
        question="Un utilisateur simple (base.group_user) a-t-il un acces en ecriture ?",
        resolved_models=["maintenance.request"],
        tool_map={"who_has_access_to": fake_tool},
    )
    # who_has_access_targets/security_locks_targets read the real graph;
    # bypass them here since only the truncation limit is under test.
    import code_intelligence.agent.predispatch_access as mod
    orig_targets = mod.who_has_access_targets if hasattr(mod, "who_has_access_targets") else None

    def _fake_targets(question, concept, G):
        return list(concept.resolved_models)

    def _fake_locks_targets(concept, G):
        return []

    from unittest.mock import patch
    with patch("code_intelligence.agent.forced_dispatch_predicates.who_has_access_targets", _fake_targets), \
         patch("code_intelligence.agent.forced_dispatch_predicates.security_locks_targets", _fake_locks_targets), \
         patch("code_intelligence.rules.security_locks.gate_observation", side_effect=lambda **kw: (kw["observation"], [])):
        dispatch_who_has_access_to(ctx)

    assert ctx.tool_observations, "no observation recorded -- dispatcher did not run"
    recorded = ctx.tool_observations[0]
    # Not truncated to (approximately) the old hardcoded 3000 -- proves the
    # call site is no longer using that literal.
    assert len(recorded) > 3100, (
        f"observation length {len(recorded)} looks capped near the old "
        "hardcoded 3000 -- predispatch_access.py may have regressed to a "
        "literal instead of reading PER_TOOL_OBSERVATION_CAPS"
    )


def test_truncate_observation_for_budget_respects_the_new_cap_directly():
    """Unit-level confirmation of _truncate_observation_for_budget itself
    with the who_has_access_to cap, isolated from the dispatcher."""
    ctx = _make_ctx(question="q", resolved_models=["x"], tool_map={})
    text = "Y" * 9500
    out = _truncate_observation_for_budget(
        ctx, text, PER_TOOL_OBSERVATION_CAPS["who_has_access_to"],
    )
    assert len(out) >= 9500  # not truncated, well under the 11000 cap

    text_too_big = "Z" * 12000
    out2 = _truncate_observation_for_budget(
        ctx, text_too_big, PER_TOOL_OBSERVATION_CAPS["who_has_access_to"],
    )
    assert len(out2) < 12000  # truncated this time
