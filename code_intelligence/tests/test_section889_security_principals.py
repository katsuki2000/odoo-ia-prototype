"""
code_intelligence/tests/test_section889_security_principals.py

todo/contexte.txt sections 888/889: F1, mandated by pmm. SAL-Q1 compares
two hypothetical personas (salesperson, portal_user) explicitly named in
the question -- but _override_user_groups_arg always overwrote the tool's
group context with the REAL demandeur's groups (always [] in benchmark),
so neither persona's ir.rule ever got evaluated correctly, regardless of
what the LLM asked for.

Fix: a harness-declared, immutable `security_principals` dict (bank JSON
-> runner state -> DispatchContext), resolved via an explicit
`principal_id` tool argument -- never via LLM-supplied group xml_ids,
which are always ignored/overridden either way.

Covers pmm's mandated test list exactly:
  1. SAL-Q1 triggers two real evaluate_record_rules calls, one per
     principal, and each actually retrieves its own rule.
  2. An invented group in user_groups_json is always overridden/ignored.
  3. An unknown principal_id is refused.
  4. Without security_principals, production behaviour (real demandeur)
     is unchanged.
  5. MNT-Q1's real data is ready to be migrated the same way
     (equipment_rule_user resolves correctly given the persona's groups)
     -- without actually touching the bank entry yet (scope: SAL-Q1 only).
  6. PUR-Q1 and STK-Q1 (bank entries) are untouched by this change.
"""

import json

import pytest

from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.tool_helpers import set_graph_ref
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tools.access import evaluate_record_rules, evaluate_rules_raw
from code_intelligence.agent.tools.structure import button_execution_path
from code_intelligence.agent.context import DispatchContext, _tool_call_key
from code_intelligence.agent.dispatch_guards import _override_user_groups_arg, UnknownPrincipalError
from code_intelligence.agent.loop import execute_tool_calls


SAL_Q1_PRINCIPALS = {
    "salesperson": ["sales_team.group_sale_salesman"],
    "portal_user": ["base.group_portal"],
}


@pytest.fixture(scope="module")
def G():
    graph = get_code_intelligence_graph()
    set_graph_ref(graph)
    return graph


class FakeConcept:
    resolved_models = ["sale.order"]
    resolved_modules = []
    is_resolved = True


class FakeTraceLogger:
    def log_hop(self, *a, **k):
        pass


def _make_ctx(G, security_principals=None, resolved_user_group_xmlids=None):
    return DispatchContext(
        G=G, concept=FakeConcept(), question="SAL-Q1", tool_map={t.name: t for t in ALL_CI_TOOLS},
        resolved_user_group_xmlids=resolved_user_group_xmlids,
        trace_logger=FakeTraceLogger(), trace_id="test", hop_cap=6,
        security_principals=security_principals or {},
    )


class FakeMsg:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


# ── 1. Tool schema exposes principal_id ─────────────────────────────────

class TestToolSchemaExposesPrincipalId:
    def test_evaluate_record_rules_declares_principal_id(self):
        assert "principal_id" in evaluate_record_rules.args

    def test_button_execution_path_declares_principal_id(self):
        assert "principal_id" in button_execution_path.args


# ── 2. SAL-Q1: two real calls, each retrieves its own rule ──────────────

class TestSalQ1TwoPrincipals:
    def test_two_distinct_calls_each_find_the_right_rule(self, G):
        ctx = _make_ctx(G, security_principals=SAL_Q1_PRINCIPALS, resolved_user_group_xmlids=[])
        msg = FakeMsg([
            {"name": "evaluate_record_rules", "id": "t1", "args": {
                "model_name": "sale.order", "permission": "write", "principal_id": "salesperson",
            }},
            {"name": "evaluate_record_rules", "id": "t2", "args": {
                "model_name": "sale.order", "permission": "write", "principal_id": "portal_user",
            }},
        ])
        messages = []
        execute_tool_calls(ctx, msg, messages)

        assert len(ctx.tool_observations) == 2
        salesperson_obs, portal_obs = ctx.tool_observations

        applicable_block = salesperson_obs.split("Règles de Groupe ignorées")[0]
        assert "sale_order_personal_rule" in applicable_block
        assert "sale_order_rule_portal" not in applicable_block

        applicable_block_portal = portal_obs.split("Règles de Groupe ignorées")[0]
        assert "sale_order_rule_portal" in applicable_block_portal
        assert "sale_order_personal_rule" not in applicable_block_portal

    def test_two_principals_are_not_deduped_as_the_same_call(self):
        k1 = _tool_call_key("evaluate_record_rules", {"model_name": "sale.order", "principal_id": "salesperson"})
        k2 = _tool_call_key("evaluate_record_rules", {"model_name": "sale.order", "principal_id": "portal_user"})
        assert k1 != k2

    def test_direct_rule_evaluation_matches_reference_answer(self, G):
        r1 = evaluate_rules_raw("sale.order", "write", json.dumps(SAL_Q1_PRINCIPALS["salesperson"]))
        assert "sale_order_personal_rule" in r1.summary_text
        r2 = evaluate_rules_raw("sale.order", "write", json.dumps(SAL_Q1_PRINCIPALS["portal_user"]))
        assert "sale_order_rule_portal" in r2.summary_text


# ── 3. Invented group in user_groups_json always overridden ─────────────

class TestInventedGroupAlwaysOverridden:
    def test_llm_supplied_groups_ignored_with_principal_id(self):
        args = {
            "model_name": "sale.order",
            "principal_id": "salesperson",
            "user_groups_json": json.dumps(["base.group_system"]),
        }
        out = _override_user_groups_arg("evaluate_record_rules", dict(args), [], SAL_Q1_PRINCIPALS)
        assert json.loads(out["user_groups_json"]) == SAL_Q1_PRINCIPALS["salesperson"]

    def test_llm_supplied_groups_ignored_without_principal_id(self):
        args = {"model_name": "sale.order", "user_groups_json": json.dumps(["base.group_system"])}
        out = _override_user_groups_arg("evaluate_record_rules", dict(args), ["base.group_user"], {})
        assert json.loads(out["user_groups_json"]) == ["base.group_user"]


# ── 4. Unknown principal_id refused ──────────────────────────────────────

class TestUnknownPrincipalRefused:
    def test_raises_unknown_principal_error(self):
        with pytest.raises(UnknownPrincipalError):
            _override_user_groups_arg(
                "evaluate_record_rules",
                {"model_name": "sale.order", "principal_id": "ghost"},
                [], SAL_Q1_PRINCIPALS,
            )

    def test_execute_tool_calls_surfaces_refusal_without_invoking_tool(self, G):
        ctx = _make_ctx(G, security_principals=SAL_Q1_PRINCIPALS, resolved_user_group_xmlids=[])
        msg = FakeMsg([{
            "name": "evaluate_record_rules", "id": "t1",
            "args": {"model_name": "sale.order", "principal_id": "ghost"},
        }])
        messages = []
        execute_tool_calls(ctx, msg, messages)
        assert len(ctx.tool_observations) == 0
        assert len(messages) == 1
        assert "refuse" in messages[0].content.lower()


# ── 5. Without security_principals, production behaviour unchanged ──────

class TestProductionPathUnchanged:
    def test_real_demandeur_groups_used_when_no_principals_declared(self, G):
        ctx = _make_ctx(G, security_principals={}, resolved_user_group_xmlids=["base.group_user"])
        msg = FakeMsg([{
            "name": "evaluate_record_rules", "id": "t1",
            "args": {"model_name": "sale.order", "permission": "write"},
        }])
        messages = []
        execute_tool_calls(ctx, msg, messages)
        assert len(ctx.tool_observations) == 1
        # base.group_user matches none of sale.order's named group rules --
        # same result as before this section existed.
        obs = ctx.tool_observations[0]
        applicable_block = obs.split("Règles de Groupe ignorées")[0]
        assert "sale_order_personal_rule" not in applicable_block
        assert "sale_order_rule_portal" not in applicable_block

    def test_absent_state_key_vs_explicit_empty_list(self):
        """Section 888/889 key-semantics fix: DispatchContext must be able
        to carry None (identity unavailable) distinctly from [] (identity
        known, no groups) -- both still fail closed identically downstream,
        this only tests the distinction is representable."""
        ctx_unset = _make_ctx(get_code_intelligence_graph(), resolved_user_group_xmlids=None)
        ctx_empty = _make_ctx(get_code_intelligence_graph(), resolved_user_group_xmlids=[])
        assert ctx_unset.resolved_user_group_xmlids is None
        assert ctx_empty.resolved_user_group_xmlids == []
        # every consumer must fail closed identically for both
        assert (ctx_unset.resolved_user_group_xmlids or []) == (ctx_empty.resolved_user_group_xmlids or [])


# ── 6. MNT-Q1 ready to migrate (not migrated yet) ────────────────────────

class TestMntQ1ReadyToMigrate:
    def test_equipment_rule_user_resolves_for_the_named_persona(self, G):
        """MNT-Q1's own question names 'base.group_user, sans
        group_equipment_manager' -- same class of bug as SAL-Q1. Confirms
        the same mechanism would retrieve equipment_rule_user once migrated,
        without touching tests/native_n1_question_bank.json for MNT-Q1 in
        this isolated commit (pmm's mandate: SAL-Q1 only, for now)."""
        r = evaluate_rules_raw("maintenance.equipment", "write", json.dumps(["base.group_user"]))
        applicable_block = r.summary_text.split("ignorées")[0]
        assert "equipment_rule_user" in applicable_block


# ── 7. PUR-Q1 / STK-Q1 untouched ─────────────────────────────────────────

class TestBankNonRegression:
    def test_pur_q1_and_stk_q1_have_no_security_principals(self):
        with open("tests/native_n1_question_bank.json", encoding="utf-8") as f:
            bank = json.load(f)
        by_id = {item["id"]: item for item in bank["questions"]}
        assert "security_principals" not in by_id["PUR-Q1"]
        assert "security_principals" not in by_id["STK-Q1"]

    def test_sal_q1_has_the_two_expected_principals(self):
        with open("tests/native_n1_question_bank.json", encoding="utf-8") as f:
            bank = json.load(f)
        by_id = {item["id"]: item for item in bank["questions"]}
        principals = by_id["SAL-Q1"]["security_principals"]
        assert set(principals.keys()) == {"salesperson", "portal_user"}
        assert principals["salesperson"]["group_xmlids"] == ["sales_team.group_sale_salesman"]
        assert principals["portal_user"]["group_xmlids"] == ["base.group_portal"]
