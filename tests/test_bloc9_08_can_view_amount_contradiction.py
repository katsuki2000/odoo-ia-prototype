"""
tests/test_bloc9_08_can_view_amount_contradiction.py

 08c follow-up (2026-08-14): tests for _correct_can_view_amount_contradictions
and its helpers (rag/graph.py) -- the synthesis-inversion detector/neutralizer
for the can_view_amount_v2 deterministic fact, symmetric to module 5/8's Bug 2
fix (_correct_override_cascade_contradictions).

Covers:
  - _has_can_view_amount_fact / _extract_can_view_amount_verdict: detection
  - _split_before_first_fact_marker: the cutoff fix for the auto-collision
    found in sandbox testing (2026-08-14) where the appended fact's own
    "l'utilisateur PEUT voir" sentence matched the ALLOW/DENY regex against
    itself.
  - _correct_can_view_amount_contradictions: the three inversion cases
    (fact=True but prose denies, fact=False but prose allows, fact=None/
    indéterminé but prose asserts either) and the no-op cases (no fact
    present, no contradiction, correct prose already).
"""


from core.graph.graph import (
    _has_can_view_amount_fact,
    _extract_can_view_amount_verdict,
    _split_before_first_fact_marker,
    _correct_can_view_amount_contradictions,
    _format_can_view_amount_fact,
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

class TestHasCanViewAmountFact:
    def test_true_verdict_fact_detected(self):
        text = "Bla bla.\n\n" + _format_can_view_amount_fact(60000, True)
        assert _has_can_view_amount_fact(text) is True

    def test_false_verdict_fact_detected(self):
        text = "Bla bla.\n\n" + _format_can_view_amount_fact(60000, False)
        assert _has_can_view_amount_fact(text) is True

    def test_indeterminate_fact_detected(self):
        text = "Bla bla.\n\n" + _format_can_view_amount_fact(60000, None, ["company_id"])
        assert _has_can_view_amount_fact(text) is True

    def test_no_fact_not_detected(self):
        assert _has_can_view_amount_fact("Une réponse ordinaire sans fait déterministe.") is False


class TestExtractCanViewAmountVerdict:
    def test_extracts_true(self):
        text = _format_can_view_amount_fact(40000, True)
        assert _extract_can_view_amount_verdict(text) is True

    def test_extracts_false(self):
        text = _format_can_view_amount_fact(60000, False)
        assert _extract_can_view_amount_verdict(text) is False

    def test_indeterminate_extracts_none(self):
        text = _format_can_view_amount_fact(60000, None, ["company_id"])
        assert _extract_can_view_amount_verdict(text) is None

    def test_no_fact_extracts_none(self):
        assert _extract_can_view_amount_verdict("rien à voir ici") is None


class TestSplitBeforeFirstFactMarker:
    def test_splits_at_first_fait_marker(self):
        text = "Prose ici. " + "[FAIT DÉTERMINISTIQUE] contenu du fait."
        assert _split_before_first_fact_marker(text) == "Prose ici. "

    def test_no_marker_returns_whole_text(self):
        text = "Juste de la prose, aucun marqueur."
        assert _split_before_first_fact_marker(text) == text

    def test_auto_collision_avoided(self):
        """The exact bug found in sandbox testing: once the fact's own
        'l'utilisateur PEUT voir' sentence is appended, the cutoff must
        exclude it from the scanned prose -- otherwise the ALLOW regex
        would match the fact block itself."""
        fact_block = _format_can_view_amount_fact(40000, True)
        full_text = "Réponse correcte sans contradiction.\n\n" + fact_block
        prose = _split_before_first_fact_marker(full_text)
        assert "PEUT" not in prose
        assert "[FAIT" not in prose


# ---------------------------------------------------------------------------
# _correct_can_view_amount_contradictions -- the three inversion cases
# ---------------------------------------------------------------------------

class TestNoOpCases:
    def test_no_op_when_no_fact_present(self):
        text = "L'utilisateur ne peut pas voir cet enregistrement selon nos règles."
        assert _correct_can_view_amount_contradictions(text) == text

    def test_no_op_when_fact_true_and_prose_agrees(self):
        fact_block = _format_can_view_amount_fact(30000, True)
        text = "L'utilisateur peut voir cet avoir de 30000€.\n\n" + fact_block
        assert _correct_can_view_amount_contradictions(text) == text

    def test_no_op_when_fact_false_and_prose_agrees(self):
        fact_block = _format_can_view_amount_fact(80000, False)
        text = "L'utilisateur ne peut pas voir cet avoir de 80000€.\n\n" + fact_block
        assert _correct_can_view_amount_contradictions(text) == text

    def test_no_op_when_indeterminate_and_prose_is_appropriately_uncertain(self):
        fact_block = _format_can_view_amount_fact(60000, None, ["company_id"])
        text = (
            "Il n'est pas possible de déterminer avec certitude si l'accès "
            "est autorisé, faute d'information sur la société.\n\n" + fact_block
        )
        assert _correct_can_view_amount_contradictions(text) == text

    def test_no_op_on_correct_answer_matching_real_08c_scenario(self):
        """The real  08c fixture: a correct answer should never be
        altered by this corrector."""
        fact_block = _format_can_view_amount_fact(60000, False)
        text = (
            "La société du document diffère de celle de l'utilisateur, donc "
            "la règle globale de cantonnement société s'applique et "
            "l'utilisateur ne peut pas voir cet enregistrement.\n\n" + fact_block
        )
        assert _correct_can_view_amount_contradictions(text) == text


class TestInversionCaseFactFalseProseAllows:
    """The exact  08c failure shape: engine says False, LLM prose says
    the user peut voir."""

    def test_replaces_allow_sentence_when_fact_is_false(self):
        fact_block = _format_can_view_amount_fact(60000, False)
        text = (
            "L'administrateur système a le permission de voir ce document de "
            "60000€ car il a des permissions élevées.\n\n" + fact_block
        )
        result = _correct_can_view_amount_contradictions(text)
        assert "NE PEUT PAS voir" in result
        assert "a le permission de voir" not in result
        # The fact block itself must be untouched.
        assert fact_block in result

    def test_replaces_peut_voir_sentence_when_fact_is_false(self):
        fact_block = _format_can_view_amount_fact(60000, False)
        text = "L'utilisateur peut voir ce document.\n\n" + fact_block
        result = _correct_can_view_amount_contradictions(text)
        assert "NE PEUT PAS voir" in result
        assert "L'utilisateur peut voir ce document." not in result


class TestInversionCaseFactTrueProseDenies:
    def test_replaces_deny_sentence_when_fact_is_true(self):
        fact_block = _format_can_view_amount_fact(30000, True)
        text = "L'utilisateur ne peut pas voir ce document.\n\n" + fact_block
        result = _correct_can_view_amount_contradictions(text)
        assert "L'utilisateur PEUT voir" in result
        assert "ne peut pas voir" not in result.split("[FAIT")[0]

    def test_replaces_pas_le_droit_sentence_when_fact_is_true(self):
        fact_block = _format_can_view_amount_fact(30000, True)
        text = "Le demandeur n'a pas le permission de voir ce document.\n\n" + fact_block
        result = _correct_can_view_amount_contradictions(text)
        assert "PEUT voir" in result
        assert "n'a pas le permission" not in result


class TestInversionCaseIndeterminateProseRoundsToCertainty:
    def test_replaces_allow_assertion_when_indeterminate(self):
        fact_block = _format_can_view_amount_fact(60000, None, ["company_id"])
        text = "L'utilisateur peut voir ce document sans restriction.\n\n" + fact_block
        result = _correct_can_view_amount_contradictions(text)
        assert "ne peut pas déterminer avec certitude" in result
        assert "peut voir ce document sans restriction" not in result

    def test_replaces_deny_assertion_when_indeterminate(self):
        fact_block = _format_can_view_amount_fact(60000, None, ["company_id"])
        text = "L'utilisateur ne peut pas voir ce document.\n\n" + fact_block
        result = _correct_can_view_amount_contradictions(text)
        assert "ne peut pas déterminer avec certitude" in result


class TestIdempotence:
    def test_running_twice_is_stable(self):
        fact_block = _format_can_view_amount_fact(60000, False)
        text = "L'utilisateur peut voir ce document.\n\n" + fact_block
        once = _correct_can_view_amount_contradictions(text)
        twice = _correct_can_view_amount_contradictions(once)
        assert once == twice


# ---------------------------------------------------------------------------
# Section 639/716 (todo/contexte.txt) -- regression tests for the two gaps
# found in production benchmark runs:
#   (639) .search() only fixed the FIRST match -- a false-positive sentence
#         matching the trigger phrase before the real contradiction consumed
#         the single correction, leaving the real one untouched.
#   (716) a bare "Oui"/"Non" verdict (isolated, or leading a fully argued
#         paragraph) is invisible to the verb-phrase regexes entirely, even
#         with (639) fixed -- observed verbatim in Q6.2 of the adversarial
#         benchmark ("Oui, s'il appartient à la même société que l'avoir.").
# ---------------------------------------------------------------------------

class TestMultiMatchNoLongerConsumedByFalsePositive:
    """Section 639: a first, harmless sentence containing the trigger phrase
    (e.g. restating what a rule *would* mean) must not prevent a LATER, real
    contradicting sentence from also being corrected."""

    def test_both_allow_sentences_corrected_when_indeterminate(self):
        fact_block = _format_can_view_amount_fact(80000, None, ["company_id"])
        text = (
            "En général, un responsable peut voir ce type de document sans "
            "problème particulier. Mais ici, l'utilisateur peut voir cet "
            "avoir de 80000€ sans restriction.\n\n" + fact_block
        )
        result = _correct_can_view_amount_contradictions(text)
        prose = result.split("[FAIT")[0]
        assert "peut voir" not in prose.lower() or "ne peut pas déterminer" in prose
        assert "sans restriction" not in prose
        assert "sans problème particulier" not in prose

    def test_first_false_positive_no_longer_shields_second_real_sentence(self):
        """The literal Section 639 shape: the FIRST regex match is a harmless
        aside, the SECOND is the real inversion -- both must be neutralized."""
        fact_block = _format_can_view_amount_fact(30000, True)
        text = (
            "Un utilisateur qui n'a pas le permission de voir en temps normal "
            "resterait bloqué. Mais dans ce cas précis, l'utilisateur ne peut "
            "pas voir ce document.\n\n" + fact_block
        )
        result = _correct_can_view_amount_contradictions(text)
        prose = result.split("[FAIT")[0]
        assert "ne peut pas voir ce document" not in prose
        assert "PEUT voir" in prose


class TestLeadingBareVerdictWhenIndeterminate:
    """Section 716: a bare 'Oui'/'Non' -- isolated or leading a justified
    paragraph -- must be corrected even without any verb-phrase trigger."""

    def test_isolated_oui_before_correct_sentence_is_corrected(self):
        fact_block = _format_can_view_amount_fact(80000, None, ["company_id", "amount_total"])
        text = (
            "Oui.\nLe reste de l'analyse est correctement incertain à ce "
            "sujet.\n\n" + fact_block
        )
        result = _correct_can_view_amount_contradictions(text)
        prose = result.split("[FAIT")[0]
        assert not prose.strip().lower().startswith("oui")

    def test_oui_with_justification_no_trigger_phrase_is_corrected(self):
        """The exact Q6.2 shape (todo/contexte.txt Section 716): 'Oui, <condition>'
        contains none of 'peut voir'/'autorisé à' -- must still be caught."""
        fact_block = _format_can_view_amount_fact(80000, None, ["company_id"])
        text = (
            "### Peut-il voir l'avoir de 80 000 € ?\n\n"
            "Oui, s'il appartient à la même société que l'avoir.\n\n"
            "Reste du raisonnement.\n\n" + fact_block
        )
        result = _correct_can_view_amount_contradictions(text)
        prose = result.split("[FAIT")[0]
        assert "Oui, s'il appartient à la même société" not in prose
        assert "ne peut pas déterminer avec certitude" in prose
        # The restated-question header is not itself a verdict -- left untouched.
        assert "Peut-il voir l'avoir de 80 000 € ?" in prose

    def test_non_isolated_when_indeterminate_is_corrected(self):
        fact_block = _format_can_view_amount_fact(80000, None, ["company_id"])
        text = "Non, ce n'est pas possible.\n\n" + fact_block
        result = _correct_can_view_amount_contradictions(text)
        prose = result.split("[FAIT")[0]
        assert not prose.strip().lower().startswith("non")


class TestLeadingVerdictNeverAppliedOutsideIndeterminateBranch:
    """A bare 'Oui'/'Non' is a CORRECT answer when the fact is determinate --
    the leading-verdict pattern must never fire in the True/False branches,
    only the specific wrong-direction ALLOW/DENY regexes."""

    def test_correct_oui_left_untouched_when_verdict_true(self):
        fact_block = _format_can_view_amount_fact(30000, True)
        text = "Oui, l'utilisateur peut voir ce document.\n\n" + fact_block
        assert _correct_can_view_amount_contradictions(text) == text

    def test_correct_non_left_untouched_when_verdict_false(self):
        fact_block = _format_can_view_amount_fact(80000, False)
        text = "Non, l'utilisateur ne peut pas voir ce document.\n\n" + fact_block
        assert _correct_can_view_amount_contradictions(text) == text
