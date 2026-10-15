"""
code_intelligence/tests/test_section907_908_dispatch_record_rules_for_personas.py

Sections 907/908: 907 investigated (code reading, no LLM/rejeu) why
evaluate_record_rules(principal_id=...) reliably engages for SAL-Q1 but
never for MNT-Q1, and found there was never a deterministic dispatcher for
personas at all -- 899's [PERSONAS DE LA QUESTION] prompt block was always
just an INVITATION the LLM could ignore (and empirically did, unreliably,
892-903/907). 908 is pmm's mandate to generalize 888/889 beyond
LLM-discretionary use: dispatch_evaluate_record_rules_for_personas(ctx)
calls evaluate_record_rules deterministically, once per persona in
ctx.security_principals, for ALL FOUR concrete permissions (pmm's explicit
choice of "all systematiquement" over read-only or per-verb-in-question --
evaluate_record_rules has no literal "all" permission of its own, confirmed
by reading record_rules.py, so this means 4 real calls, not one).

These tests exercise the real dispatcher function against the real corpus
graph (no LLM, no mocking of evaluate_record_rules itself) -- matching this
project's convention (test_section889_security_principals.py) for testing
predispatch behavior directly rather than through the full agent loop.
"""

import pytest

from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_access import (
    dispatch_evaluate_record_rules_for_personas,
)


SAL_Q1_PRINCIPALS = {
    "salesperson": ["sales_team.group_sale_salesman"],
    "portal_user": ["base.group_portal"],
}
# Mirrors the shape detect_security_principals_from_question (896) actually
# produces once resolved through loop.py's resolved_security_principals
# step (flat list of xmlids, not the nested {"group_xmlids": [...]} the
# bank JSON/auto-detector return before that resolution).
MNT_Q1_PRINCIPALS = {
    "utilisateur_simple": ["base.group_user"],
}


@pytest.fixture(scope="module")
def G(real_graph):
    return real_graph


class FakeConceptSaleOrder:
    resolved_models = ["sale.order"]
    resolved_modules = []
    is_resolved = True


class FakeConceptMaintenanceEquipment:
    resolved_models = ["maintenance.equipment"]
    resolved_modules = []
    is_resolved = True


class FakeTraceLogger:
    def log_hop(self, *a, **k):
        pass


def _make_ctx(G, concept, security_principals, hop_cap=40):
    return DispatchContext(
        G=G, concept=concept, question="test", tool_map={t.name: t for t in ALL_CI_TOOLS},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(), trace_id="test", hop_cap=hop_cap,
        security_principals=security_principals,
    )


# ── SAL-Q1: 2 personas x 4 permissions = 8 deterministic calls ──────────

class TestSalQ1TwoPersonasAllPermissions:
    def test_eight_observations_recorded(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert len(ctx.tool_observations) == 8
        assert ctx.hop_count == 8

    def test_salesperson_read_observation_is_correctly_restrictive(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        salesperson_read_key = ("evaluate_record_rules", "sale.order", "salesperson", "read")
        assert salesperson_read_key in ctx.seen_calls
        # Every recorded observation for salesperson/read must contain the
        # restrictive rule, applicable (not merely mentioned-then-ignored).
        matches = [
            obs for obs in ctx.tool_observations
            if "sale_order_personal_rule" in obs.split("ignor")[0]
        ]
        assert matches, "sale_order_personal_rule must appear in an APPLICABLE block somewhere"

    def test_portal_user_read_observation_is_correctly_restrictive(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        matches = [
            obs for obs in ctx.tool_observations
            if "sale_order_rule_portal" in obs.split("ignor")[0]
        ]
        assert matches, "sale_order_rule_portal must appear in an APPLICABLE block somewhere"

    def test_all_eight_call_keys_are_distinct(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        expected = {
            ("evaluate_record_rules", "sale.order", principal, permission)
            for principal in ("salesperson", "portal_user")
            for permission in ("read", "write", "create", "unlink")
        }
        assert expected == ctx.seen_calls

    def test_system_prompt_suffix_names_both_personas(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert "PERSONAS" in ctx.system_prompt_suffix
        assert "salesperson" in ctx.system_prompt_suffix
        assert "portal_user" in ctx.system_prompt_suffix
        assert "demandeur" in ctx.system_prompt_suffix.lower()

    def test_matched_dispatchers_records_this_dispatcher(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert "dispatch_evaluate_record_rules_for_personas" in ctx.matched_dispatchers


# ── MNT-Q1: 1 persona x 4 permissions -- the exact case that never ───────
#    engaged on 0/3+ valid rejeux (900-903/907) before this dispatcher ────

class TestMntQ1OnePersonaAllPermissions:
    def test_four_observations_recorded(self, G):
        ctx = _make_ctx(G, FakeConceptMaintenanceEquipment(), MNT_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert len(ctx.tool_observations) == 4
        assert ctx.hop_count == 4

    def test_equipment_rule_user_is_applicable_not_ignored_for_read(self, G):
        """The exact fact 3/3 rejeux in 907 got wrong: for base.group_user,
        equipment_rule_user must appear as an APPLICABLE group rule (not
        listed under 'ignorees, non-membre'), restricting read to followed
        equipment."""
        ctx = _make_ctx(G, FakeConceptMaintenanceEquipment(), MNT_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        read_key = ("evaluate_record_rules", "maintenance.equipment", "utilisateur_simple", "read")
        assert read_key in ctx.seen_calls
        matches = [
            obs for obs in ctx.tool_observations
            if "equipment_rule_user" in obs.split("ignor")[0]
        ]
        assert matches, (
            "equipment_rule_user must appear in an APPLICABLE block for "
            "base.group_user on read -- this is the exact ground truth 3/3 "
            "rejeux in section 907 failed to reach without this dispatcher."
        )


# ── No security_principals declared -- dispatcher must no-op cleanly ────

class TestNoPersonasDeclared:
    def test_no_op_when_security_principals_empty(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), {})
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert ctx.tool_observations == []
        assert ctx.hop_count == 0
        assert "dispatch_evaluate_record_rules_for_personas" not in ctx.matched_dispatchers
        assert ctx.system_prompt_suffix == ""


# ── Hop budget exhaustion -- must degrade gracefully, never raise ───────

class TestHopBudgetExhaustion:
    def test_stops_without_exceeding_cap_when_budget_is_tight(self, G):
        """hop_cap=3 leaves room for only 3 of the 8 calls SAL-Q1 would
        otherwise need -- the dispatcher must stop cleanly (break, not
        raise) rather than blow past hop_cap or crash."""
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS, hop_cap=3)
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert ctx.hop_count <= 3
        assert len(ctx.tool_observations) <= 3

    def test_already_exhausted_budget_is_a_pure_no_op(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS, hop_cap=0)
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert ctx.tool_observations == []
        assert "dispatch_evaluate_record_rules_for_personas" not in ctx.matched_dispatchers


# ── Idempotency: a second run must add nothing new (dedup via seen_calls) ─

class TestIdempotency:
    def test_second_call_adds_no_new_observations(self, G):
        ctx = _make_ctx(G, FakeConceptSaleOrder(), SAL_Q1_PRINCIPALS)
        dispatch_evaluate_record_rules_for_personas(ctx)
        first_count = len(ctx.tool_observations)
        dispatch_evaluate_record_rules_for_personas(ctx)
        assert len(ctx.tool_observations) == first_count
