"""
miro-rag/code_intelligence/tests/test_bloc9_05_link_guard_backfill.py

Bloc 9 gap, module 5/8 (custom_asset_loan, 2026-08-10, bloc9-05c-no-link-trap):
locks in the deterministic backfill layer in rag/graph.py -- _extract_link_guard_fields
and _backfill_link_guard_clarifications -- the second half of the fix (extraction-layer
coverage for exception_conditions/exception_guard_fields/[GARDE DE LIEN] itself lives in
test_s2_5_semgrep_locks.py).

Same principle as the earlier required-groups backfill (_backfill_missing_required_groups):
rather than trusting the small synthesis LLM to correctly reason about Python's `and`
short-circuit direction from raw condition text alone -- which a live run showed it get
backwards even when the condition was quoted to it verbatim -- the verdict is computed
deterministically at extraction time and unconditionally restated in the final answer.
No mocks: exercises the real regex/backfill functions directly against realistic raw
tool-output text, same convention as the rest of the test suite.
"""

from core.graph import (
    _extract_link_guard_fields,
    _backfill_link_guard_clarifications,
    _scoped_raw_tool_output,
    _answer_contradicts_link_guard,
    _neutralize_contradicting_link_guard_sentence,
)


# Realistic raw tool-output fragment, matching semgrep_locks_analyzer.py's actual
# summary_text rendering for the real custom_asset_loan/models/asset_loan.py shape.
_RAW_OUTPUT_WITH_GUARD = """\
Analyse des verrous Python ([asset_loan.py:L1-L30](file:///home/user/odoo-17.0/addons/custom_asset_loan/models/asset_loan.py#L1-L30)) [Confiance: HIGH]:
  - Security lock messages (UserError/ValidationError):
    * "Separation des roles requise : le beneficiaire d'un materiel de plus de 2000 euros doit etre different du demandeur initial." (condition : rec.demande_achat_liee_id and rec.demande_achat_liee_id.montant_estime > 2000)
      [GARDE DE LIEN: si 'rec.demande_achat_liee_id' est vide/absent (aucun enregistrement lie), cette condition est FAUSSE par court-circuit Python (evaluation de gauche a droite d'un 'and') -- la regle ci-dessus NE S'APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]
"""

_RAW_OUTPUT_WITHOUT_GUARD = """\
Analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH]:
  - Security lock messages (UserError/ValidationError):
    * "Seul un responsable comptable peut valider un avoir de plus de 5000e."
"""


class TestExtractLinkGuardFields:
    def test_extracts_field_name_when_annotation_present(self):
        fields = _extract_link_guard_fields(_RAW_OUTPUT_WITH_GUARD)
        assert fields == ["rec.demande_achat_liee_id"]

    def test_returns_empty_list_when_no_annotation_present(self):
        assert _extract_link_guard_fields(_RAW_OUTPUT_WITHOUT_GUARD) == []

    def test_deduplicates_repeated_field_across_multiple_findings(self):
        doubled = _RAW_OUTPUT_WITH_GUARD + "\n" + _RAW_OUTPUT_WITH_GUARD
        assert _extract_link_guard_fields(doubled) == ["rec.demande_achat_liee_id"]

    def test_empty_string_input_returns_empty_list(self):
        assert _extract_link_guard_fields("") == []


class TestBackfillLinkGuardClarifications:
    def test_appends_deterministic_fact_when_guard_present(self):
        """Core regression test (bloc9-05c-no-link-trap): the backfill must
        ALWAYS append the computed conclusion when a [GARDE DE LIEN]
        annotation exists in the raw tool output -- unconditional on
        question wording. Uses a NEUTRAL (non-contradicting) input here on
        purpose: this test is about the unconditional-append behavior in
        isolation, not the contradiction/replacement behavior, which has
        its own dedicated coverage below (TestLinkGuardContradictionDetectionAndCorrection,
        TestNeutralizeContradictingLinkGuardSentence) -- a wrong-polarity
        input here would now be partially rewritten by
        _neutralize_contradicting_link_guard_sentence (2026-08-11 fix),
        which is a different mechanism than the one this test locks in.
        """
        original_answer = (
            "La mise à disposition ne peut pas être démarrée dans ce cas "
            "précis, pour le matériel concerné."  # neutral, no wrong-polarity phrasing
        )
        result = _backfill_link_guard_clarifications(original_answer, _RAW_OUTPUT_WITH_GUARD)

        assert "[FAIT DÉTERMINISTIQUE] Court-circuit" in result
        assert "rec.demande_achat_liee_id" in result
        assert "NE S'APPLIQUE PAS" in result
        # Original (neutral, non-contradicting) LLM text is kept, not
        # replaced -- the backfill supplements with an authoritative fact,
        # it does not touch prose that isn't asserting the wrong polarity.
        assert original_answer in result

    def test_noop_when_no_guard_field_in_raw_output(self):
        """Must never fabricate a link-guard clarification for a lock that
        has no such shape (e.g. the plain has_group()/amount-threshold
        lock in custom_credit_note_approval) -- a false positive here would
        be actively misleading."""
        original_answer = "Seul un responsable comptable peut valider cet avoir."
        result = _backfill_link_guard_clarifications(original_answer, _RAW_OUTPUT_WITHOUT_GUARD)
        assert result == original_answer

    def test_idempotent_when_marker_already_present(self):
        """If a future/different synthesis run already got it right and
        happened to include the exact marker sentence on its own, the
        backfill must not duplicate it."""
        already_correct = (
            "[FAIT DÉTERMINISTIQUE] Court-circuit ET (déterministe) : "
            "la règle ne s'applique pas si rec.demande_achat_liee_id est vide."
        )
        result = _backfill_link_guard_clarifications(already_correct, _RAW_OUTPUT_WITH_GUARD)
        assert result == already_correct
        assert result.count("[FAIT DÉTERMINISTIQUE] Court-circuit") == 1

    def test_noop_on_empty_raw_output(self):
        original_answer = "Réponse sans observation associée."
        result = _backfill_link_guard_clarifications(original_answer, "")
        assert result == original_answer


# Bloc 9 gap, module 5/8 Bug 2 (2026-08-11, bloc9-05c-no-link-trap, fixed last
# per the user's own stated priority order): a live run showed the backfill
# doing exactly what it was designed to do (append the correct verdict) while
# the LLM's own prose, directly above it, asserted the opposite conclusion --
# 'la règle... s'applique quand même, quel que soit le montant'. The fact was
# technically present in the answer, but not the first or most prominent
# thing the user would read. This class covers the detection + the
# authoritative correction banner _backfill_link_guard_clarifications now
# prepends when that happens.
class TestLinkGuardContradictionDetectionAndCorrection:
    def test_detects_real_confirmed_wrong_polarity_phrasing(self):
        """Exact phrasing from the live bloc9-05c-no-link-trap failure,
        not a hypothetical paraphrase."""
        wrong = (
            "La règle de séparation des rôles (bénéficiaire différent du "
            "demandeur) s'applique quand même, quel que soit le montant du "
            "matériel, dans le cas où une mise à disposition de matériel "
            "n'est pas reliée à aucune demande d'achat."
        )
        assert _answer_contradicts_link_guard(wrong) is True

    def test_does_not_flag_a_correct_answer(self):
        correct = (
            "La mise à disposition ne peut pas être démarrée. Si "
            "rec.demande_achat_liee_id est vide ou absent, alors la condition "
            "est considérée comme fausse et la règle n'est pas appliquée."
        )
        assert _answer_contradicts_link_guard(correct) is False

    def test_does_not_flag_the_backfilled_footer_itself(self):
        """The deterministic footer's own wording ('NE S'APPLIQUE PAS') must
        never trip the contradiction pattern on its own -- it is the
        correct verdict, not the bug."""
        footer_only = (
            "[FAIT DÉTERMINISTIQUE] Court-circuit ET (déterministe) : la "
            "règle ne s'applique pas si rec.demande_achat_liee_id est vide."
        )
        assert _answer_contradicts_link_guard(footer_only) is False

    def test_backfill_replaces_contradicting_sentence_with_correct_conclusion(self):
        """2026-08-11 revision: a prepended banner alone was confirmed on a
        real rerun to still leave the exact wrong sentence readable right
        below it (scripts/check_bloc9_05_asset_loan_e2e.py's forbidden_markers
        check still failed on it, and this product's audience is non-dev end
        users who should not need to notice a caveat to get the right answer)
        -- the backfill now replaces the wrong sentence in place instead."""
        wrong_answer = (
            "La règle s'applique quand même, quel que soit le montant du "
            "matériel."
        )
        result = _backfill_link_guard_clarifications(wrong_answer, _RAW_OUTPUT_WITH_GUARD)
        # the wrong claim itself must be gone, not just preceded by a banner
        assert "s'applique quand même" not in result
        assert "CORRECTION AUTOMATIQUE" not in result
        assert "NE S'APPLIQUE PAS" in result
        # the deterministic footer is still appended too, independently of
        # the in-place sentence replacement
        assert "[FAIT DÉTERMINISTIQUE] Court-circuit" in result

    def test_backfill_leaves_correct_answer_unchanged(self):
        correct_answer = (
            "La règle ne s'applique pas si aucune demande d'achat n'est liée."
        )
        result = _backfill_link_guard_clarifications(correct_answer, _RAW_OUTPUT_WITH_GUARD)
        assert correct_answer in result
        assert "CORRECTION AUTOMATIQUE" not in result


class TestNeutralizeContradictingLinkGuardSentence:
    """Direct unit coverage of the sentence-replacement helper itself,
    independent of the backfill wiring above."""

    def test_replaces_the_real_confirmed_wrong_sentence_verbatim(self):
        """Exact phrasing from the live bloc9-05c-no-link-trap rerun
        (2026-08-11), not a hypothetical paraphrase -- confirms the
        sentence-boundary regex matches the real failure shape end to end,
        including the trailing subordinate clause after the matched
        fragment (', dans le cas où...')."""
        wrong = (
            "La règle de séparation des rôles (bénéficiaire différent du "
            "demandeur) s'applique quand même, quel que soit le montant du "
            "matériel, dans le cas où une mise à disposition de matériel "
            "n'est pas reliée à aucune demande d'achat."
        )
        result = _neutralize_contradicting_link_guard_sentence(wrong, ["rec.demande_achat_liee_id"])
        assert "s'applique quand même" not in result
        assert "NE s'applique PAS" in result
        assert "rec.demande_achat_liee_id" in result

    def test_noop_when_no_contradiction_present(self):
        correct = "La règle ne s'applique pas en l'absence de demande d'achat liée."
        assert _neutralize_contradicting_link_guard_sentence(correct, ["rec.demande_achat_liee_id"]) == correct

    def test_handles_alternate_confirmed_phrasing_malgre(self):
        wrong = "La règle s'applique malgré l'absence de demande d'achat liée."
        result = _neutralize_contradicting_link_guard_sentence(wrong, ["rec.demande_achat_liee_id"])
        assert "s'applique malgré" not in result
        assert "NE s'applique PAS" in result


class TestScopedRawToolOutput:
    """Bloc 9 gap, module 5/8 continued (2026-08-11, contamination found
    on 05c-no-link-trap): _extract_link_guard_fields used to be fed the
    ENTIRE raw_tool_output (every hop of the whole ReAct turn), so when
    the loop wandered onto an unrelated model in the same turn (confirmed
    real case: a custom.purchase.request detour while answering a
    custom.asset.loan question), that unrelated model's OWN [GARDE DE
    LIEN] annotation leaked into a backfill that is supposed to be a
    100%-reliable, model-scoped fact. _scoped_raw_tool_output restricts
    the text handed to a backfill to observations recorded against the
    model(s) the question actually resolved to."""

    def test_excludes_observation_from_unrelated_model(self):
        """Core regression test: two observations in the same turn, one
        for the target model (custom.asset.loan) and one for an unrelated
        model the ReAct loop happened to visit (custom.purchase.request,
        the confirmed contamination source) -- scoping to the target
        model must drop the unrelated model's [GARDE DE LIEN]
        annotation."""
        purchase_observation = (
            "Analyse des verrous Python (purchase_request.py) [Confiance: HIGH]:\n"
            "  - Security lock messages (UserError/ValidationError):\n"
            "    * \"Validation requise.\" (condition : not (user_ok or email_ok))\n"
            "      [GARDE DE LIEN: si 'not (user_ok or email_ok)' est vide/absent "
            "(aucun enregistrement lie), cette condition est FAUSSE par court-circuit "
            "Python (evaluation de gauche a droite d'un 'and') -- la regle ci-dessus "
            "NE S'APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]"
        )
        observations = [purchase_observation, _RAW_OUTPUT_WITH_GUARD]
        models = ["custom.purchase.request", "custom.asset.loan"]

        scoped = _scoped_raw_tool_output(observations, models, ["custom.asset.loan"])

        assert "rec.demande_achat_liee_id" in scoped
        assert "not (user_ok or email_ok)" not in scoped

        fields = _extract_link_guard_fields(scoped)
        assert fields == ["rec.demande_achat_liee_id"]

    def test_keeps_observation_with_unknown_model(self):
        """An observation with no recorded model (meta/global tool call)
        is never the source of cross-model contamination, so it must be
        kept regardless of target_models -- excluding it would only lose
        legitimate content for no safety benefit."""
        observations = [_RAW_OUTPUT_WITH_GUARD, "Observation sans modele associe."]
        models = ["custom.asset.loan", ""]

        scoped = _scoped_raw_tool_output(observations, models, ["custom.asset.loan"])

        assert "rec.demande_achat_liee_id" in scoped
        assert "Observation sans modele associe." in scoped

    def test_falls_back_to_unscoped_when_target_models_empty(self):
        """Unresolved concept (no target model) must not silently drop
        everything -- falls back to the full unscoped concatenation, same
        behavior as before this fix."""
        observations = [_RAW_OUTPUT_WITH_GUARD, _RAW_OUTPUT_WITHOUT_GUARD]
        models = ["custom.asset.loan", "custom.credit.note.approval"]

        scoped = _scoped_raw_tool_output(observations, models, [])

        assert scoped == "\n\n".join(observations)

    def test_end_to_end_contamination_scenario_produces_correct_backfill(self):
        """Full pipeline: scope first, then backfill -- the fields list fed
        to _backfill_link_guard_clarifications must be pure, so the
        deterministic fact appended never mixes fields across models."""
        purchase_observation = (
            "[GARDE DE LIEN: si 'not (user_ok or email_ok)' est vide/absent "
            "(aucun enregistrement lie), cette condition est FAUSSE par court-circuit "
            "Python (evaluation de gauche a droite d'un 'and') -- la regle ci-dessus "
            "NE S'APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]"
        )
        observations = [purchase_observation, _RAW_OUTPUT_WITH_GUARD]
        models = ["custom.purchase.request", "custom.asset.loan"]

        scoped = _scoped_raw_tool_output(observations, models, ["custom.asset.loan"])
        original_answer = "La regle ne s'applique jamais sans demande d'achat liee."
        result = _backfill_link_guard_clarifications(original_answer, scoped)

        assert "rec.demande_achat_liee_id" in result
        assert "not (user_ok or email_ok)" not in result
