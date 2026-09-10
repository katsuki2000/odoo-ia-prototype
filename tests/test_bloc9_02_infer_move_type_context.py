# -*- coding: utf-8 -*-
"""
tests/test_bloc9_02_infer_move_type_context.py

Bug B2 (module 02,  section 96 -> 98, option (a) chosen
and implemented): rag.ci_helpers._infer_move_type_context.

Investigation (section 98) found the matched business alias was never
actually LOST anywhere in the pipeline -- it survives all the way to
ResolvedConcept.user_term, in scope at both _dispatch_context/context
construction call sites in code_intelligence_agent() (rag/ci_agent_node.py).
The gap was simply that nothing read it for this purpose. This locks the
inference function itself: append-only signal, Regle 5 discipline (never
guess on ambiguity or on a non-static-alias resolution path).
"""

import pytest

from code_intelligence.agent.business_resolver import ResolvedConcept
from code_intelligence.agent.ci_agent_node.context.context_extractors import _infer_move_type_context


def _static_alias(user_term: str, models=None) -> ResolvedConcept:
    return ResolvedConcept(
        user_term=user_term,
        resolved_models=models or ["account.move"],
        confidence=1.0,
        source_step="static_alias",
        is_resolved=True,
        reason=f"Matched static aliases: {user_term}",
    )


class TestInfersUnambiguousMoveType:
    def test_avoir_infers_out_refund(self):
        concept = _static_alias("avoir")
        assert _infer_move_type_context(concept) == {"move_type": "out_refund"}

    def test_avoirs_plural_infers_out_refund(self):
        concept = _static_alias("avoirs")
        assert _infer_move_type_context(concept) == {"move_type": "out_refund"}

    def test_credit_note_english_alias_infers_out_refund(self):
        concept = _static_alias("credit note")
        assert _infer_move_type_context(concept) == {"move_type": "out_refund"}

    def test_facture_infers_out_invoice(self):
        concept = _static_alias("facture")
        assert _infer_move_type_context(concept) == {"move_type": "out_invoice"}

    def test_facturation_infers_out_invoice(self):
        concept = _static_alias("facturation")
        assert _infer_move_type_context(concept) == {"move_type": "out_invoice"}

    def test_multiple_matched_terms_same_move_type_still_resolves(self):
        # resolve_business_term joins every matched alias key with ", " --
        # two aliases from the SAME group (e.g. a question phrased in a way
        # that trips both "avoir" and "avoirs" patterns) must still resolve
        # unambiguously, not be treated as a conflict.
        concept = _static_alias("avoir, avoirs")
        assert _infer_move_type_context(concept) == {"move_type": "out_refund"}


class TestNoGuessOnAmbiguityOrMissingSignal:
    def test_conflicting_terms_returns_empty(self):
        # A question naming both "avoir" and "facture" -- two DIFFERENT
        # move_types implied -- must never be guessed either way.
        concept = _static_alias("avoir, facture")
        assert _infer_move_type_context(concept) == {}

    def test_unrelated_alias_returns_empty(self):
        concept = _static_alias("mise a disposition", models=["custom.asset.loan"])
        assert _infer_move_type_context(concept) == {}

    def test_none_concept_returns_empty(self):
        assert _infer_move_type_context(None) == {}

    def test_unresolved_concept_returns_empty(self):
        concept = ResolvedConcept(user_term="et pour cette annee ?", is_resolved=False, source_step="unresolved")
        assert _infer_move_type_context(concept) == {}

    def test_non_static_alias_source_step_returns_empty(self):
        """The exact-technical-mention / fuzzy_graph_match / llm_arbitration
        paths set user_term to the raw question text, not a clean alias
        list -- scanning that for 'avoir'/'facture' substrings would be an
        unreliable, unintended use of this function's contract. Must
        return {} even if the raw question text happens to contain 'avoir'
        as a substring somewhere unrelated."""
        concept = ResolvedConcept(
            user_term="peut-on voir cet avoir exceptionnel dans le module de congés ?",
            resolved_models=["hr.leave"],
            confidence=1.0,
            source_step="fuzzy_graph_match",
            is_resolved=True,
            reason="fuzzy matched",
        )
        assert _infer_move_type_context(concept) == {}

    def test_exact_technical_mention_source_step_returns_empty(self):
        concept = ResolvedConcept(
            user_term="peut-il consulter un avoir concernant account.move ?",
            resolved_models=["account.move"],
            confidence=1.0,
            source_step="exact_technical_mention",
            is_resolved=True,
            reason="exact technical mention",
        )
        assert _infer_move_type_context(concept) == {}


class TestIntegrationWithCanViewAmountV2:
    """End-to-end sanity check: the inferred move_type actually resolves
    module 02's real global rule , instead
    of poisoning the Kleene OR the way an empty context does."""

    def test_module_02_global_rule_resolves_with_inferred_move_type(self):
        from code_intelligence.knowledge_rules.deterministic.access.record_rules_models import RuleDetail, RuleEvaluationResult

        global_rule = RuleDetail(
            rule_xml_id="custom_credit_note_visibility_rules.rule_avoir_cantonnement_societe",
            rule_name="Avoirs - cantonnement societe",
            domain_force="['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]",
            groups=[],
        )
        result = RuleEvaluationResult(
            model_name="account.move",
            user_groups=[],
            applied_global_rules=[global_rule],
            applied_group_rules=[],
        )

        concept = _static_alias("avoir")
        context = {"amount": 80000}
        context.update(_infer_move_type_context(concept))
        # Same company as the requester -- second OR leaf also resolves,
        # so the whole rule is conclusively True (no longer indeterminate).
        context.update({"company_id": 1, "user": {"company_id": {"id": 1}}})

        can_view, unresolved = result.can_view_amount_v2(context)
        assert can_view is True
        assert unresolved == []

    def test_without_move_type_the_rule_stays_indeterminate(self):
        """Regression guard: confirms the pre-fix symptom (section 96) is
        real -- this mirrors the actual 02a/02b scenario, where no company
        is mentioned in the question either (_extract_company_context also
        returns {} there), so BOTH leaves of the OR are unresolved and the
        rule cannot conclude."""
        from code_intelligence.knowledge_rules.deterministic.access.record_rules_models import RuleDetail, RuleEvaluationResult

        global_rule = RuleDetail(
            rule_xml_id="custom_credit_note_visibility_rules.rule_avoir_cantonnement_societe",
            rule_name="Avoirs - cantonnement societe",
            domain_force="['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]",
            groups=[],
        )
        result = RuleEvaluationResult(
            model_name="account.move",
            user_groups=[],
            applied_global_rules=[global_rule],
            applied_group_rules=[],
        )

        context = {"amount": 80000}
        can_view, unresolved = result.can_view_amount_v2(context)
        assert can_view is None
        assert "move_type" in unresolved
        assert "company_id" in unresolved

    def test_move_type_alone_without_company_still_indeterminate(self):
        """Confirms the fix is a partial, honest improvement, not a full
        resolution on its own: inferring move_type closes ONE of the two
        unresolved leaves (B1-style Regle-5 discipline), but company_id is
        still never guessed -- if the question also depends on company
        context, the verdict correctly stays indeterminate rather than
        silently resolving on move_type alone."""
        from code_intelligence.knowledge_rules.deterministic.access.record_rules_models import RuleDetail, RuleEvaluationResult

        global_rule = RuleDetail(
            rule_xml_id="custom_credit_note_visibility_rules.rule_avoir_cantonnement_societe",
            rule_name="Avoirs - cantonnement societe",
            domain_force="['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]",
            groups=[],
        )
        result = RuleEvaluationResult(
            model_name="account.move",
            user_groups=[],
            applied_global_rules=[global_rule],
            applied_group_rules=[],
        )

        concept = _static_alias("avoir")
        context = {"amount": 80000}
        context.update(_infer_move_type_context(concept))

        can_view, unresolved = result.can_view_amount_v2(context)
        assert can_view is None
        assert "company_id" in unresolved
        assert "move_type" not in unresolved
