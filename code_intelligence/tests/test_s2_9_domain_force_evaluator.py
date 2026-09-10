"""
code_intelligence/tests/test_s2_9_domain_force_evaluator.py

Tests for evaluate_domain_force() (safe AST domain_force parser + Kleene
three-valued evaluator) and RuleEvaluationResult.can_view_amount_v2()
(tri-state successor to can_view_amount()).

Root cause covered:  08c  -- can_view_amount()
fails OPEN (returns True) on any domain_force it cannot fully parse via
its amount-only regex, because it never sees non-amount conditions like
company_id at all. Fixtures below use the REAL domain_force strings from
/home/user/odoo-17.0/addons/custom_deep_inheritance_security/security/
security_rules.xml (module 08, custom_deep_document), not invented text:

  Rule 1 (global, "Cantonnement Societe"):
    ['|', ('company_id', '=', False), ('company_id', '=', user.company_id.id)]

  Rule 2 (group base.group_user, "Regle Imbriquee Complexe"):
    ['&', '|', ('amount', '<=', 50000), ('user_id', '=', user.id),
     ('company_id', '=', user.company_id.id)]
"""

import pytest

from code_intelligence.deterministic.access.record_rules_models import RuleDetail, RuleEvaluationResult
from code_intelligence.deterministic.access.domain_evaluator import evaluate_domain_force


# ---------------------------------------------------------------------------
# evaluate_domain_force() -- parser + Kleene evaluator, in isolation
# ---------------------------------------------------------------------------

class TestEvaluateDomainForceBasics:
    def test_empty_domain_matches_everything(self):
        verdict, unresolved = evaluate_domain_force("", {})
        assert verdict is True
        assert unresolved == []

    def test_true_leaf_marker(self):
        verdict, unresolved = evaluate_domain_force("[(1, '=', 1)]", {})
        assert verdict is True
        assert unresolved == []

    def test_id_not_false_marker_is_unconditionally_true(self):
        verdict, unresolved = evaluate_domain_force("[('id', '!=', False)]", {})
        assert verdict is True
        assert unresolved == []

    def test_simple_amount_leaf_true(self):
        verdict, unresolved = evaluate_domain_force(
            "[('amount', '<=', 50000)]", {"amount": 40000}
        )
        assert verdict is True
        assert unresolved == []

    def test_simple_amount_leaf_false(self):
        verdict, unresolved = evaluate_domain_force(
            "[('amount', '<=', 50000)]", {"amount": 60000}
        )
        assert verdict is False
        assert unresolved == []

    def test_missing_field_is_unresolved_none(self):
        verdict, unresolved = evaluate_domain_force(
            "[('amount', '<=', 50000)]", {}
        )
        assert verdict is None
        assert unresolved == ["amount"]

    def test_malformed_domain_force_returns_none(self):
        verdict, unresolved = evaluate_domain_force("not a domain at all !!", {})
        assert verdict is None
        assert unresolved == []


class TestEvaluateDomainForceDynamicRef:
    """Dotted user.* references resolved against context['user'], never
    via eval()/exec() or a live Odoo environment."""

    def test_user_company_match_resolves_true(self):
        verdict, unresolved = evaluate_domain_force(
            "[('company_id', '=', user.company_id.id)]",
            {"company_id": 3, "user": {"company_id": {"id": 3}}},
        )
        assert verdict is True
        assert unresolved == []

    def test_user_company_mismatch_resolves_false(self):
        verdict, unresolved = evaluate_domain_force(
            "[('company_id', '=', user.company_id.id)]",
            {"company_id": 3, "user": {"company_id": {"id": 7}}},
        )
        assert verdict is False
        assert unresolved == []

    def test_missing_user_context_is_unresolved(self):
        verdict, unresolved = evaluate_domain_force(
            "[('company_id', '=', user.company_id.id)]",
            {"company_id": 3},
        )
        assert verdict is None
        assert "user" in unresolved or "company_id" in unresolved


class TestEvaluateDomainForceRealModule08Rule1Global:
    """
    Rule 1 from custom_deep_inheritance_security -- the exact global rule
    behind the  08c fail-open: ['|', ('company_id', '=', False),
    ('company_id', '=', user.company_id.id)].
    """

    DOMAIN = "['|', ('company_id', '=', False), ('company_id', '=', user.company_id.id)]"

    def test_company_id_false_short_circuits_true_via_or(self):
        # First OR branch alone is enough -- company_id False, regardless
        # of what user.company_id.id resolves to.
        verdict, unresolved = evaluate_domain_force(
            self.DOMAIN, {"company_id": False, "user": {"company_id": {"id": 3}}}
        )
        assert verdict is True
        assert unresolved == []

    def test_same_company_resolves_true(self):
        verdict, unresolved = evaluate_domain_force(
            self.DOMAIN, {"company_id": 3, "user": {"company_id": {"id": 3}}}
        )
        assert verdict is True
        assert unresolved == []

    def test_different_company_resolves_false_not_true(self):
        """
        The exact  08c scenario: the question explicitly states the
        company differs. The old can_view_amount() regex could not see
        company_id at all and failed open (True). evaluate_domain_force
        must resolve this to False, not silently allow.
        """
        verdict, unresolved = evaluate_domain_force(
            self.DOMAIN, {"company_id": 3, "user": {"company_id": {"id": 9}}}
        )
        assert verdict is False
        assert unresolved == []

    def test_missing_company_context_is_honestly_unresolved(self):
        """
        When neither branch of the OR can be resolved (company_id itself
        missing from context), the honest answer is None ("cannot
        conclude"), never a guessed True or False.
        """
        verdict, unresolved = evaluate_domain_force(self.DOMAIN, {})
        assert verdict is None
        assert "company_id" in unresolved


class TestEvaluateDomainForceRealModule08Rule2NestedAndOr:
    """
    Rule 2 from custom_deep_inheritance_security -- nested AND/OR:
    ['&', '|', ('amount', '<=', 50000), ('user_id', '=', user.id),
     ('company_id', '=', user.company_id.id)]
    i.e. (amount <= 50000 OR user_id == user.id) AND company_id == user.company_id.id
    """

    DOMAIN = (
        "['&', '|', ('amount', '<=', 50000), ('user_id', '=', user.id), "
        "('company_id', '=', user.company_id.id)]"
    )

    def test_amount_under_threshold_and_same_company_is_true(self):
        verdict, unresolved = evaluate_domain_force(
            self.DOMAIN,
            {
                "amount": 40000,
                "user_id": 99,
                "company_id": 3,
                "user": {"id": 1, "company_id": {"id": 3}},
            },
        )
        assert verdict is True
        assert unresolved == []

    def test_amount_over_threshold_but_owner_is_true_via_or(self):
        verdict, unresolved = evaluate_domain_force(
            self.DOMAIN,
            {
                "amount": 60000,
                "user_id": 1,
                "company_id": 3,
                "user": {"id": 1, "company_id": {"id": 3}},
            },
        )
        assert verdict is True
        assert unresolved == []

    def test_amount_over_threshold_and_not_owner_is_false(self):
        verdict, unresolved = evaluate_domain_force(
            self.DOMAIN,
            {
                "amount": 60000,
                "user_id": 42,
                "company_id": 3,
                "user": {"id": 1, "company_id": {"id": 3}},
            },
        )
        assert verdict is False
        assert unresolved == []

    def test_or_branch_true_but_and_fails_on_company_is_false(self):
        # amount satisfies the OR, but the outer AND still fails because
        # company differs -- confirms AND/OR nesting is respected, not
        # flattened.
        verdict, unresolved = evaluate_domain_force(
            self.DOMAIN,
            {
                "amount": 10000,
                "user_id": 99,
                "company_id": 3,
                "user": {"id": 1, "company_id": {"id": 9}},
            },
        )
        assert verdict is False
        assert unresolved == []


# ---------------------------------------------------------------------------
# RuleEvaluationResult.can_view_amount_v2() -- combines global (AND) +
# group (OR) rules via evaluate_domain_force, mirroring can_view_amount()'s
# combination convention but tri-state and field-aware.
# ---------------------------------------------------------------------------

def _module08_global_rule() -> RuleDetail:
    return RuleDetail(
        rule_xml_id="custom_deep_inheritance_security.rule_deep_document_company",
        rule_name="Documents Profonds - Cantonnement Societe",
        domain_force="['|', ('company_id', '=', False), ('company_id', '=', user.company_id.id)]",
        groups=[],
    )


def _module08_group_rule() -> RuleDetail:
    return RuleDetail(
        rule_xml_id="custom_deep_inheritance_security.rule_deep_document_complex_nested",
        rule_name="Documents Profonds - Regle Imbriquee Complexe",
        domain_force=(
            "['&', '|', ('amount', '<=', 50000), ('user_id', '=', user.id), "
            "('company_id', '=', user.company_id.id)]"
        ),
        groups=["base.group_user"],
    )


class TestCanViewAmountV2NoGroupRules:
    """No applied group rules -- same convention as can_view_amount():
    only global rules restrict, group absence never restricts."""

    def test_global_rule_satisfied_no_group_rules_is_true(self):
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=[],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[],
        )
        verdict, unresolved = result.can_view_amount_v2(
            {"company_id": 3, "user": {"company_id": {"id": 3}}}
        )
        assert verdict is True
        assert unresolved == []

    def test_global_rule_violated_different_company_is_false(self):
        """The confirmed  08c fix: differs from the old
        can_view_amount(), which would have returned True here because its
        regex never saw the company_id condition at all."""
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=[],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[],
        )
        verdict, unresolved = result.can_view_amount_v2(
            {"company_id": 3, "user": {"company_id": {"id": 9}}}
        )
        assert verdict is False
        assert unresolved == []

    def test_missing_context_is_honestly_none_not_defaulted_to_true(self):
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=[],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[],
        )
        verdict, unresolved = result.can_view_amount_v2({})
        assert verdict is None
        assert "company_id" in unresolved


class TestCanViewAmountV2WithGroupRules:
    """Global AND group(s) combined, group rules OR'd among themselves --
    same structural convention as can_view_amount(), computed via the
    tri-state evaluator instead of a regex."""

    def _context(self, *, company_id=3, user_company_id=3, amount=40000, user_id=99, requester_id=1):
        return {
            "company_id": company_id,
            "amount": amount,
            "user_id": user_id,
            "user": {"id": requester_id, "company_id": {"id": user_company_id}},
        }

    def test_global_and_group_both_satisfied_is_true(self):
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=["base.group_user"],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[_module08_group_rule()],
        )
        verdict, unresolved = result.can_view_amount_v2(self._context())
        assert verdict is True
        assert unresolved == []

    def test_global_satisfied_but_group_rule_denies_is_false(self):
        # Same company (global OK), but amount over threshold AND not the
        # record owner (group rule's inner AND/OR fails) -> overall False.
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=["base.group_user"],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[_module08_group_rule()],
        )
        verdict, unresolved = result.can_view_amount_v2(
            self._context(amount=60000, user_id=42, requester_id=1)
        )
        assert verdict is False
        assert unresolved == []

    def test_global_rule_fails_short_circuits_to_false_even_if_group_would_pass(self):
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=["base.group_user"],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[_module08_group_rule()],
        )
        verdict, unresolved = result.can_view_amount_v2(
            self._context(company_id=3, user_company_id=9)
        )
        assert verdict is False
        assert unresolved == []

    def test_unresolved_group_field_propagates_none_when_global_is_true(self):
        # Global rule resolves True (same company); group rule's amount/
        # user_id fields are simply absent from context -> tri-state None,
        # not a guessed True or False, and the missing fields are named.
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=["base.group_user"],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[_module08_group_rule()],
        )
        verdict, unresolved = result.can_view_amount_v2(
            {"company_id": 3, "user": {"id": 1, "company_id": {"id": 3}}}
        )
        assert verdict is None
        assert "amount" in unresolved
        assert "user_id" in unresolved

    def test_multiple_applied_group_rules_are_ored(self):
        # A second, unconditionally-true group rule (TRUE_LEAF marker) OR'd
        # alongside the complex nested one -- OR means the group-rule
        # portion is satisfied even if the nested rule alone would fail.
        true_leaf_group_rule = RuleDetail(
            rule_xml_id="fixture.rule_always_true",
            rule_name="Toujours Vrai (fixture)",
            domain_force="[(1, '=', 1)]",
            groups=["base.group_system"],
        )
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=["base.group_user", "base.group_system"],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[_module08_group_rule(), true_leaf_group_rule],
        )
        verdict, unresolved = result.can_view_amount_v2(
            self._context(amount=60000, user_id=42, requester_id=1)
        )
        assert verdict is True
        assert unresolved == []


class TestCanViewAmountV2CoexistsWithCanViewAmount:
    """can_view_amount_v2 is additive -- the original bool-only method
    keeps its prior (regex-based, fail-open) behavior unchanged for
    existing callers that haven't opted in yet."""

    def test_can_view_amount_unaffected_by_v2_addition(self):
        result = RuleEvaluationResult(
            model_name="custom.deep.document",
            user_groups=[],
            applied_global_rules=[_module08_global_rule()],
            applied_group_rules=[],
        )
        # Old method still only looks for a "<=" amount pattern in
        # domain_force; this global rule has none, so it stays True
        # (the known, documented fail-open behavior can_view_amount_v2
        # exists to fix, not silently patch in place).
        assert result.can_view_amount(60000) is True
