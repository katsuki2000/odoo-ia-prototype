"""
todo/contexte.txt section 911: two deterministic relays extending the
workflow predispatch chain, both triggered by real failures observed on
the Bloc N1 Workflow (Q2) questions --

(A) dispatch_describe_workflow (predispatch_structure.py): when
    describe_workflow comes back with its "no explicit workflow state
    transitions defined" marker (a stage_id/kanban-driven model --
    describe_workflow only analyzes the `state` field), relay
    deterministically to read_source_code on the model's own write(),
    resolved via the graph (resolve_method_override_chain), instead of
    leaving the LLM to guess a method name (MNT-Q2 guessed 'action_done',
    absent from the graph for maintenance.request).

(B) dispatch_button_execution_path (predispatch_structure.py): when the
    button's own body (already fetched via read_source_code) calls another
    button_* method of the same model by name, follow that call
    automatically via the graph instead of leaving the LLM to guess a line
    range for it (PUR-Q2: button_confirm calls order.button_approve(), the
    LLM guessed lines 520-560, past the real definition at 491-495, and
    never saw it -- confirmed by captures/reasoning_trace.jsonl hop 4).

Uses the real knowledge graph (no mocking of graph content) -- these
dispatchers' whole point is deterministic graph resolution, so a fake
graph would not exercise the real failure mode being fixed.
"""

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import pytest

from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.tool_helpers import set_graph_ref
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.predispatch_structure import (
    dispatch_describe_workflow,
    dispatch_button_execution_path,
    _WORKFLOW_EMPTY_MARKER,
)


class _FakeTraceLogger:
    def log_hop(self, **kwargs):
        pass


@pytest.fixture(scope="module")
def G():
    graph = get_code_intelligence_graph()
    set_graph_ref(graph)
    return graph


@pytest.fixture
def tool_map():
    return {t.name: t for t in ALL_CI_TOOLS}


def _make_ctx(G, tool_map, question, models):
    from code_intelligence.agent.context import DispatchContext

    class _Concept:
        is_resolved = True
        resolved_models = models

    return DispatchContext(
        G=G, concept=_Concept(), question=question, tool_map=tool_map,
        resolved_user_group_xmlids=[], trace_logger=_FakeTraceLogger(),
        trace_id="test-911", hop_cap=20,
    )


# ── (A) dispatch_describe_workflow -- write() relay on empty observation ──

def test_mnt_q2_empty_workflow_relays_to_write(G, tool_map):
    """maintenance.request: describe_workflow is empty (stage_id-based) --
    the dispatcher must fetch write() automatically instead of leaving the
    LLM with nothing but the empty marker."""
    ctx = _make_ctx(
        G, tool_map,
        "Que se passe-t-il automatiquement quand une demande de maintenance "
        "preventive et recurrente (recurring_maintenance=True) atteint une "
        "etape marquee 'done' ?",
        ["maintenance.request"],
    )
    dispatch_describe_workflow(ctx)

    assert ctx.tool_observation_tools == ["describe_workflow", "read_source_code"]
    assert _WORKFLOW_EMPTY_MARKER in ctx.tool_observations[0]
    write_obs = ctx.tool_observations[1]
    assert "def write" in write_obs
    assert ctx.tool_observation_models[1] == "maintenance.request"
    assert "STAGE-BASED MODEL(S)" in ctx.system_prompt_suffix
    assert "maintenance.request" in ctx.system_prompt_suffix
    assert "action_done" in ctx.system_prompt_suffix  # named as the trap to avoid


def test_non_empty_workflow_model_no_relay(G, tool_map):
    """Non-regression: a model with real `state` transitions (purchase.order)
    must NOT trigger the write() relay -- describe_workflow's own output is
    sufficient, nothing empty to fall back from."""
    ctx = _make_ctx(
        G, tool_map,
        "Que se passe-t-il quand on clique sur Confirm Order ?",
        ["purchase.order"],
    )
    dispatch_describe_workflow(ctx)

    assert ctx.tool_observation_tools == ["describe_workflow"]
    assert "STAGE-BASED MODEL(S)" not in ctx.system_prompt_suffix


def test_empty_marker_constant_matches_workflow_rules_module():
    """The marker string this dispatcher keys off of must stay byte-for-byte
    in sync with the one describe_workflow() actually emits
    (code_intelligence/rules/workflow.py) -- a silent drift here would
    silently disable the whole relay."""
    from code_intelligence.rules.workflow import describe_workflow as _describe_workflow_impl
    import inspect
    src = inspect.getsource(_describe_workflow_impl)
    assert _WORKFLOW_EMPTY_MARKER in src


# ── (B) dispatch_button_execution_path -- button-to-button auto-follow ──

def test_pur_q2_button_confirm_follows_button_approve(G, tool_map):
    """purchase.order/button_confirm calls order.button_approve() in its own
    body -- the dispatcher must read button_approve()'s real definition
    automatically instead of leaving the LLM to guess a line range."""
    ctx = _make_ctx(
        G, tool_map,
        "Que se passe-t-il exactement quand on clique sur 'Confirm Order' "
        "(button_confirm) selon que la commande est eligible ou non a "
        "l'approbation directe ?",
        ["purchase.order"],
    )
    dispatch_button_execution_path(ctx)

    assert ctx.tool_observation_tools[:3] == [
        "button_execution_path", "read_source_code", "read_source_code",
    ]
    button_confirm_obs = ctx.tool_observations[1]
    button_approve_obs = ctx.tool_observations[2]
    assert "def button_confirm" in button_confirm_obs
    assert "def button_approve" in button_approve_obs
    assert "'state': 'purchase'" in button_approve_obs
    assert "po_lock" in button_approve_obs
    assert "CALLED METHODS" in ctx.system_prompt_suffix


def test_button_with_no_internal_button_call_no_extra_follow(G, tool_map):
    """Non-regression: a button whose body does NOT call another button_*
    method (button_cancel: just writes state) must not trigger any extra
    read_source_code beyond the base one."""
    ctx = _make_ctx(
        G, tool_map,
        "Que se passe-t-il quand on clique sur Cancel (button_cancel) sur "
        "une commande d'achat ?",
        ["purchase.order"],
    )
    dispatch_button_execution_path(ctx)

    assert ctx.tool_observation_tools.count("read_source_code") <= 1
    assert "CALLED METHODS" not in ctx.system_prompt_suffix


def test_button_call_extraction_excludes_self_reference():
    from code_intelligence.rules.source_callees import extract_followable_callees
    body = "def button_confirm(self):\n    order.button_confirm()\n    order.button_approve()\n"
    names = extract_followable_callees(body, "button_confirm")
    assert "button_approve" in names
    assert "button_confirm" not in names


def test_dedup_key_prevents_refetch_on_second_dispatch(G, tool_map):
    """Calling the dispatcher twice on the same ctx (seen_calls carried
    over) must not re-fetch button_approve() a second time."""
    ctx = _make_ctx(
        G, tool_map,
        "Que se passe-t-il exactement quand on clique sur 'Confirm Order' "
        "(button_confirm) selon que la commande est eligible ou non a "
        "l'approbation directe ?",
        ["purchase.order"],
    )
    dispatch_button_execution_path(ctx)
    n_after_first = len(ctx.tool_observation_tools)
    ctx.matched_dispatchers.clear()
    dispatch_button_execution_path(ctx)
    assert len(ctx.tool_observation_tools) == n_after_first
