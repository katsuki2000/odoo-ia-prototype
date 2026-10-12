"""
code_intelligence/tests/test_b2_move_type_context_injection.py

Bug B2 (todo/contexte.txt sections 189-201): `_infer_move_type_context`
existed in ci_helpers.py (added during a parallel session) but was never
consumed by ci_agent_node.py's `_dispatch_context`/`context` construction
for `can_view_amount_v2`. Fixed in section 200 (import + two call sites).

This file covers two things:
  1. `_infer_move_type_context` in isolation -- every branch of its
     documented contract (static_alias-only, single-unambiguous-match-only,
     {} otherwise).
  2. The REAL, empirically-observed effect this has on `can_view_amount_v2`
     via the actual global rule from
     /home/user/odoo-17.0/addons/custom_credit_note_visibility_rules/
     security/ir_rule_layered.xml (`rule_avoir_multi_societe`):

       ['|', ('move_type', '!=', 'out_refund'),
             ('company_id', '=', user.company_id.id)]

     For a company-agnostic question (no same/different-company phrasing,
     so `_extract_company_context` contributes {}), this rule's OR needs
     EITHER branch resolved to settle the verdict. Before B2, `move_type`
     was never in context, so a "facture" question (out_invoice) could
     not short-circuit the OR to True via its first branch even though
     the answer is obvious from the business term alone -- the verdict
     stayed None (unresolved). After B2, the first branch resolves
     (move_type != 'out_refund' is unambiguously True for a facture),
     short-circuiting the whole rule to True without ever needing
     company_id. Verified empirically against this exact rule before
     writing these assertions (not invented from the docstring alone).
"""

from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.agent.context_extractors import (
    _infer_move_type_context,
    _extract_company_context,
)
from code_intelligence.rules.record_rules import RuleDetail, RuleEvaluationResult


# ---------------------------------------------------------------------------
# _infer_move_type_context() in isolation
# ---------------------------------------------------------------------------

class TestInferMoveTypeContextIsolation:
    def test_facture_resolves_to_out_invoice(self):
        concept = resolve_business_term("Qui peut voir une facture de 30000 euros ?", G=None, use_static_aliases=True)
        assert concept.source_step == "static_alias"
        assert _infer_move_type_context(concept) == {"move_type": "out_invoice"}

    def test_avoir_resolves_to_out_refund(self):
        concept = resolve_business_term("Qui peut voir un avoir de 30000 euros ?", G=None, use_static_aliases=True)
        assert concept.source_step == "static_alias"
        assert _infer_move_type_context(concept) == {"move_type": "out_refund"}

    def test_unresolved_concept_returns_empty(self):
        concept = resolve_business_term("xyzabc123 nonsense query", G=None, use_static_aliases=True)
        assert concept.is_resolved is False
        assert _infer_move_type_context(concept) == {}

    def test_none_concept_returns_empty(self):
        assert _infer_move_type_context(None) == {}

    def test_non_static_alias_source_step_returns_empty(self):
        """Per the function's own contract: user_term is only guaranteed
        to be the matched alias keys on the static_alias path -- any other
        source_step (fuzzy_graph_match, exact_technical_mention,
        llm_arbitration) must not be scanned for aliases at all."""

        class _FakeConcept:
            user_term = "un avoir de 3000"
            source_step = "fuzzy_graph_match"
            is_resolved = True

        assert _infer_move_type_context(_FakeConcept()) == {}

    def test_ambiguous_multiple_move_types_returns_empty(self):
        """Both 'avoir' and 'facture' matched in the same resolution ->
        two distinct move_types implied -> absence of a single
        unambiguous signal must resolve to {}, never a guessed value."""

        class _FakeConcept:
            user_term = "avoir, facture"
            source_step = "static_alias"
            is_resolved = True

        assert _infer_move_type_context(_FakeConcept()) == {}


# ---------------------------------------------------------------------------
# Real-world effect on can_view_amount_v2, using the actual global rule
# from custom_credit_note_visibility_rules (not an invented domain_force).
# ---------------------------------------------------------------------------

def _real_avoir_multi_societe_rule() -> RuleDetail:
    """Copied verbatim from
    custom_credit_note_visibility_rules/security/ir_rule_layered.xml,
    record id rule_avoir_multi_societe."""
    return RuleDetail(
        rule_xml_id="custom_credit_note_visibility_rules.rule_avoir_multi_societe",
        rule_name="Avoirs - cantonnement societe (regle globale, sans groupe)",
        domain_force="['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]",
        groups=[],
    )


def _evaluate_for_question(question: str, amount: float = 30000.0):
    """Mirrors ci_agent_node.py's _dispatch_context/context construction
    exactly (same three update() calls, same order) so this test tracks
    the real integration point, not just the helper in isolation."""
    concept = resolve_business_term(question, G=None, use_static_aliases=True)
    context = {"amount": amount}
    context.update(_extract_company_context(question))
    context.update(_infer_move_type_context(concept))

    result = RuleEvaluationResult(
        model_name="account.move",
        user_groups=[],
        applied_global_rules=[_real_avoir_multi_societe_rule()],
        applied_group_rules=[],
    )
    return result.can_view_amount_v2(context), context


class TestMoveTypeInjectionResolvesRealCompanyAgnosticRule:
    def test_facture_company_agnostic_question_now_resolves_true(self):
        """The key B2 regression check: before the fix, this exact
        company-agnostic facture question left can_view_amount_v2
        unresolved (None) because move_type was never in context, even
        though 'facture' unambiguously means move_type != 'out_refund',
        which alone satisfies the OR regardless of company_id."""
        (verdict, unresolved), context = _evaluate_for_question(
            "Qui peut voir une facture de 30000 euros ?"
        )
        assert context["move_type"] == "out_invoice"
        assert verdict is True
        assert unresolved == []

    def test_avoir_company_agnostic_question_still_honestly_unresolved_but_narrower(self):
        """For an actual avoir, move_type alone cannot settle the rule --
        company_id is still genuinely needed and still missing (no
        same/different-company phrasing in the question) -- so the
        verdict correctly stays None. What B2 changes here is that
        'move_type' no longer appears in unresolved: the system now knows
        for certain this IS a credit note, it just still needs the
        company to conclude."""
        (verdict, unresolved), context = _evaluate_for_question(
            "Qui peut voir un avoir de 30000 euros ?"
        )
        assert context["move_type"] == "out_refund"
        assert verdict is None
        assert "move_type" not in unresolved
        assert "company_id" in unresolved

    def test_without_move_type_injection_facture_question_was_wrongly_unresolved(self):
        """Regression pin for the pre-B2 behavior: reproduces the exact
        bug by constructing the context the OLD way (no
        _infer_move_type_context call at all), proving the fix is not a
        no-op -- the same question genuinely used to come back
        unresolved."""
        concept = resolve_business_term(
            "Qui peut voir une facture de 30000 euros ?", G=None,
            use_static_aliases=True,
        )
        assert concept.source_step == "static_alias"  # sanity: alias did match

        pre_b2_context = {"amount": 30000.0}
        pre_b2_context.update(
            _extract_company_context("Qui peut voir une facture de 30000 euros ?")
        )
        # deliberately NOT updating with _infer_move_type_context(concept)

        result = RuleEvaluationResult(
            model_name="account.move",
            user_groups=[],
            applied_global_rules=[_real_avoir_multi_societe_rule()],
            applied_group_rules=[],
        )
        verdict, unresolved = result.can_view_amount_v2(pre_b2_context)
        assert verdict is None
        assert "move_type" in unresolved
