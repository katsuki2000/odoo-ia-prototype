import pytest
from unittest.mock import patch, MagicMock

from core.schemas import AssistantResponse
from types import SimpleNamespace

from core.graph.graph import (
    generate, format_output, _parse_raw_json_answer,
    _rank_and_cap_override_methods,
    _format_can_view_amount_fact, _question_suggests_automation_bypass,
    _extract_override_modules, _backfill_missing_override_modules,
    _extract_override_chain_amounts, _backfill_missing_override_chain_amount,
    _answer_denies_other_overrides, _answer_asserts_override_shortcircuit,
    _neutralize_override_count_denial, _neutralize_override_shortcircuit_sentence,
    _correct_override_cascade_contradictions,
    _force_out_of_scope_model_answer,
    _extract_security_lock_condition_amounts, _backfill_missing_security_lock_amount,
    _amount_present_in_text,
    _extract_hardcoded_id_literals, _backfill_missing_hardcoded_id_literals,
    _detect_degenerate_growing_repetition, _strip_degenerate_growing_repetition,
    _question_is_access_related,
    _extract_company_context,
    _extract_required_groups, _extract_required_groups_for_amount,
    _backfill_missing_required_groups, _flag_ungrounded_group_xmlids,
    _block_is_custom_module_file, _restrict_blocks_to_custom_modules,
    _grounded_core_only_groups, _strip_core_only_group_mentions,
    _correct_security_lock_threshold_contradictions,
)
from document_rag.generate_node import _verify_used_sources
from config.settings import CORE_ADDONS_PATH as _TEST_CORE_ADDONS_PATH

# 1. Test fallback when no context is found
def test_generate_fallback():
    state = {
        "question": "Où est le bureau ?",
        "chat_history": [],
        "retrieved_chunks": []
    }
    result = generate(state)
    assert result["response"].answer == "Je n'ai pas de source fiable pour répondre à cette question."
    assert result["response"].confidence == 0.0
    assert len(result["response"].sources) == 0


def test_generate_out_of_scope_refuses_before_llm():
    state = {
        "question": "Raconte-moi une blague sur les ERP.",
        "chat_history": [],
        "retrieved_chunks": [
            {"document": "Odoo ERP context", "metadata": {"source": "wiki.txt"}}
        ],
    }
    result = generate(state)
    assert "Cette question ne fait pas partie de mon périmètre" in result["response"].answer
    assert result["response"].confidence == 0.0
    assert len(result["response"].sources) == 0


def test_parse_raw_json_answer_extracts_answer_field():
    raw = (
        '{"answer": "Le bouton est grisé car le document est validé.", '
        '"sources": [{"file": "account_move.py", "lines": "84"}], '
        '"confidence": 0.9, "missing_info": null}'
    )
    assert _parse_raw_json_answer(raw) == "Le bouton est grisé car le document est validé."


def test_parse_raw_json_answer_strips_markdown_fence():
    raw = '```json\n{"answer": "Réponse propre.", "confidence": 0.7}\n```'
    assert _parse_raw_json_answer(raw) == "Réponse propre."


def test_parse_raw_json_answer_returns_none_for_plain_text():
    # Not JSON-shaped -> caller should fall back to the raw text unchanged.
    assert _parse_raw_json_answer("Voici une réponse en texte libre.") is None


def test_parse_raw_json_answer_returns_none_when_answer_field_missing():
    assert _parse_raw_json_answer('{"confidence": 0.5}') is None


@patch('core.graph.graph.ChatGroq')
def test_generate_raw_invoke_fallback_parses_json_answer(mock_chat_groq):
    # Structured-output call fails -> raw invoke fallback runs. The raw
    # response.content is JSON text (SYSTEM_PROMPT instructs JSON output) --
    # generate() must surface only the 'answer' field, not the raw JSON blob.
    mock_llm_instance = MagicMock()
    mock_chat_groq.return_value = mock_llm_instance
    mock_structured_llm = MagicMock()
    mock_llm_instance.with_structured_output.return_value = mock_structured_llm
    mock_structured_llm.invoke.side_effect = Exception("Tool choice is required, but model did not call a tool")

    mock_llm_instance.invoke.return_value = SimpleNamespace(
        content='{"answer": "Le montant est masqué car seuls les responsables financiers peuvent le consulter.", '
                '"sources": [], "confidence": 0.8, "missing_info": null}'
    )

    state = {
        "question": "Pourquoi le montant est caché ?",
        "chat_history": [],
        "retrieved_chunks": [
            {"document": "context", "metadata": {"source": "rule.xml"}}
        ],
    }
    result = generate(state)
    assert result["response"].answer == (
        "Le montant est masqué car seuls les responsables financiers peuvent le consulter."
    )
    assert '"answer"' not in result["response"].answer
    assert "missing_info" not in result["response"].answer


# 2. Test format output WITHOUT OCR warning
def test_format_output_clean():
    state = {
        "response": AssistantResponse(answer="Voici la réponse.", confidence=0.8, sources=[]),
        "retrieved_chunks": [
            {"document": "test doc", "metadata": {"source": "wiki.md", "type": "wiki"}}
        ]
    }
    result = format_output(state)
    assert result["response"].ocr_warning is False
    assert "qualité de lecture est limitée" not in result["response"].answer


class TestRankAndCapOverrideMethods:
    def test_no_op_single_candidate(self):
        """ gap rerun (2026-08-11): cap lowered from 2 to 1 (see
        module-level comment above _MAX_OVERRIDE_CASCADE_DISPATCH in
        rag/graph.py) -- with only one flagged candidate to begin with,
        there is nothing to rank or drop."""
        methods = ["action_valider_avoir"]
        assert _rank_and_cap_override_methods("peu importe", methods) == methods

    def test_ranks_and_keeps_only_top_relevant_method(self):
        question = "Qui a le permission d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?"
        methods = [
            "_compute_commercial_partner_id",
            "write",
            "action_valider_avoir",
            "_reverse_moves",
        ]
        result = _rank_and_cap_override_methods(question, methods)
        assert result == ["action_valider_avoir"]

    def test_two_candidates_still_gets_capped_to_one(self):
        """ gap, module 1/8 rerun (2026-08-10/11): the exact case that
        motivated lowering the cap from 2 to 1 -- exactly 2 flagged
        candidates on a shared model, one relevant and one not. The old
        cap=2 'no-op when <= cap' guard let both through untouched here,
        wasting a full hop of CI_MAX_HOPS on the irrelevant one."""
        question = "Qui a le permission d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?"
        methods = ["_compute_commercial_partner_id", "action_valider_avoir"]
        result = _rank_and_cap_override_methods(question, methods)
        assert result == ["action_valider_avoir"]


class TestFormatCanViewAmountFact:
    def test_contains_deterministic_marker_and_verdict(self):
        text = _format_can_view_amount_fact(80000, True)
        assert "[FAIT DÉTERMINISTIQUE]" in text
        assert "80000" in text
        assert "PEUT" in text and "NE PEUT PAS" not in text

    def test_denied_verdict_says_ne_peut_pas(self):
        text = _format_can_view_amount_fact(80000, False)
        assert "NE PEUT PAS" in text

    def test_never_contains_imperative_instruction_to_the_llm(self):
        """Regression: the fact text itself must never instruct the model
        in second person (that belongs in synthesis_prompt, not in data
        the model might echo verbatim)."""
        text = _format_can_view_amount_fact(80000, True)
        lowered = text.lower()
        for banned in ("ne doit jamais", "reprendre ce verdict", "recalcul"):
            assert banned not in lowered, f"found banned imperative phrase: {banned!r}"



class TestAutomationPatternNoBareAdverbFalsePositive:
    def test_bare_automatiquement_does_not_trigger(self):
        question = (
            "Si un employé coche 'urgente' sur une demande de congé qui "
            "dépasse son solde restant, sa demande est-elle automatiquement "
            "validée, ou faut-il encore une validation supplémentaire ?"
        )
        assert _question_suggests_automation_bypass(question) is False

    def test_bare_automatique_adjective_does_not_trigger(self):
        assert _question_suggests_automation_bypass(
            "Ce processus est-il automatique ?"
        ) is False

    def test_action_automatique_still_triggers(self):
        assert _question_suggests_automation_bypass(
            "Y a-t-il une action automatique qui valide cet avoir ?"
        ) is True

    def test_automatisation_still_triggers(self):
        assert _question_suggests_automation_bypass(
            "Cette validation passe-t-elle par une automatisation cachée ?"
        ) is True

    def test_q5_1_wording_still_triggers_via_memes_regles(self):
        """Non-regression: Q5.1's actual wording never relied on the
        automatiq* branch -- 'mêmes règles' alone must keep triggering."""
        assert _question_suggests_automation_bypass(
            "Est-ce que tous les avoirs fournisseurs passent par les mêmes "
            "règles d'approbation ?"
        ) is True

    def test_bypass_and_contourner_still_trigger(self):
        assert _question_suggests_automation_bypass("Peut-on bypass cette règle ?") is True
        assert _question_suggests_automation_bypass("Comment contourner cette validation ?") is True


_REAL_OVERRIDE_CHAIN_RAW_TEXT = (
    "Chaîne de surcharge de 'account.move.action_valider_avoir' (3 modules, "
    "ordre d'exécution réel, pas l'ordre de dépendance):\n"
    "  1. module 'custom_credit_note_approval_vip' -- [account_move.py:L7-L14]\n"
    "      SUPER() NON GARDÉ: ...\n"
    "  2. module 'custom_credit_note_approval_regional' -- [account_move.py:L9-L15]\n"
    "      CHAINE RELATIONNELLE NON VÉRIFIÉE (Règle 3): 'action_valider_avoir' "
    "dépend d'une chaîne de champs Many2one enchaînés sans vérification "
    "d'existence -- _get_directeur_regional() L20: "
    "`env.user.employee_id.parent_id.parent_id.user_id` "
    "(atteint si `rec.amount_total > 20000`).\n"
    "  3. module 'custom_credit_note_approval' -- [account_move.py:L13-L22]\n"
    "     (aucun risque structurel détecté par cette heuristique pour ce module)"
)


class TestBackfillMissingOverrideModules:
    def test_extracts_all_three_modules_in_order(self):
        assert _extract_override_modules(_REAL_OVERRIDE_CHAIN_RAW_TEXT) == [
            "custom_credit_note_approval_vip",
            "custom_credit_note_approval_regional",
            "custom_credit_note_approval",
        ]

    def test_no_op_when_no_override_chain_text_present(self):
        assert _extract_override_modules("rien à voir ici") == []

    def test_backfills_base_module_dropped_by_mislabeling(self):
        """ live failure: base module correctly enumerated
        in content but labeled 'module 'account_move'' instead of its real
        name -- a plain substring check on 'custom_credit_note_approval'
        would (wrongly) still pass because it's a literal prefix of the two
        correctly-named siblings already in the answer. Real pytest run
        (2026-08-11) caught a real bug here: this exact question wording
        never matches _APPROVAL_PATTERN ('valider' is glued to underscores
        on both sides inside 'action_valider_avoir', no \\b boundary to
        match at) -- the backfill used to be gated on that pattern and
        would have silently no-op'd on this very case. Fixed by dropping
        the gate entirely (see _backfill_missing_override_modules
        docstring in rag/graph.py) -- this test is what caught it and now
        locks in the fix."""
        answer = (
            "1. Le module 'custom_credit_note_approval_vip' ...\n"
            "2. Le module 'custom_credit_note_approval_regional' ...\n"
            "3. Le module 'account_move' ..."
        )
        result = _backfill_missing_override_modules(answer, _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert "custom_credit_note_approval'" in result
        assert "[FAIT DÉTERMINISTIQUE]" in result
        # Original (mislabeled) prose is preserved, not edited/removed.
        assert "module 'account_move'" in result

    def test_no_op_when_all_modules_already_named(self):
        answer = (
            "Modules concernés : 'custom_credit_note_approval_vip', "
            "'custom_credit_note_approval_regional', 'custom_credit_note_approval'."
        )
        result = _backfill_missing_override_modules(answer, _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert result == answer

    def test_backfills_regardless_of_question_wording(self):
        """Unconditional by design (see docstring) -- the extraction step
        (modules non-empty) is the real relevance guard, not question
        vocabulary. Non-regression for the fix above: must still backfill
        even when nothing in the answer names any module at all, for a
        question with zero approval-related wording."""
        result = _backfill_missing_override_modules("réponse courte", _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert "custom_credit_note_approval_vip" in result
        assert "[FAIT DÉTERMINISTIQUE]" in result

    def test_no_op_when_raw_text_has_no_override_chain_content(self):
        result = _backfill_missing_override_modules("réponse courte", "rien à voir ici")
        assert result == "réponse courte"


class TestBackfillMissingOverrideChainAmount:
    def test_extracts_amount_without_thousands_separator(self):
        assert _extract_override_chain_amounts(_REAL_OVERRIDE_CHAIN_RAW_TEXT) == ["20000"]

    def test_no_op_when_no_amount_expression_present(self):
        assert _extract_override_chain_amounts("rien à voir ici") == []

    def test_backfills_amount_dropped_from_business_phrased_answer(self):
        """ live failure: the regional module's 20000e
        finding is present verbatim in the raw text but never used in the
        synthesized answer for the business-phrased question."""
        answer = (
            "Pour un avoir de 25 000€ pour un client normal (pas VIP), seul un "
            "responsable comptable peut valider l'avoir, car il dépasse le "
            "plafond de 5 000€."
        )
        result = _backfill_missing_override_chain_amount(answer, _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert "20000" in result
        assert "[FAIT DÉTERMINISTIQUE]" in result

    def test_no_op_when_amount_already_present_unspaced(self):
        answer = "Au-delà de 20000€, le directeur régional est notifié."
        result = _backfill_missing_override_chain_amount(answer, _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert result == answer

    def test_no_op_when_amount_already_present_with_space(self):
        answer = "Au-delà de 20 000€, le directeur régional est notifié."
        result = _backfill_missing_override_chain_amount(answer, _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert result == answer

    def test_backfills_regardless_of_question_wording(self):
        """Unconditional by design -- same fix/rationale as
        TestBackfillMissingOverrideModules.test_backfills_base_module_
        dropped_by_mislabeling above (see rag/graph.py docstring): must
        still backfill even for an answer with zero approval-related
        wording, since the amounts-list emptiness check is the real
        relevance guard."""
        result = _backfill_missing_override_chain_amount("réponse courte", _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert "20000" in result

    def test_no_op_when_raw_text_has_no_amount_expression(self):
        result = _backfill_missing_override_chain_amount("réponse courte", "rien à voir ici")
        assert result == "réponse courte"

    def test_no_op_on_unrelated_rec_comparison_outside_override_chain_text(self):
        """ gap, found 2026-08-11 (module 5/8, 
        live run, same day as module 5/8's exception_conditions fix in
        semgrep_locks_analyzer.py): _OVERRIDE_CHAIN_AMOUNT_RE ('rec.<attr> >
        <digits>') is not actually specific to
        analyze_method_override_chain's output shape -- the same literal
        pattern also appears inside exception_conditions' rendering of an
        UNRELATED model's guard clause ('condition : rec.montant_estime >
        10000 and (not email_ok)', custom_purchase_request.action_valider's
        own separate threshold, nothing to do with any method-override
        chain). Confirmed live: a custom_asset_loan question that also
        legitimately resolved custom.purchase.request (the two models are
        linked) picked up a fabricated 'la chaine de surcharge de methode
        contient une condition supplementaire declenchee au-dela de
        10000e' fact for a model that has no override chain at all. Fixture
        below mirrors the real live raw text verbatim (both models'
        analyze_security_locks blocks, no analyser_chaine_surcharge_
        methode block at all -- no 'module ''x''' line anywhere)."""
        contaminated_raw_text = (
            "Analyse des verrous Python ([asset_loan.py:L1-L30]...):\n"
            "  - Security lock messages (UserError/ValidationError):\n"
            "    * \"Separation des roles requise...\" (condition : "
            "rec.demande_achat_liee_id and rec.demande_achat_liee_id.montant_estime > 2000 "
            "and rec.demande_achat_liee_id.demandeur_id == rec.beneficiaire_id)\n\n"
            "Analyse des verrous Python ([purchase_request.py:L1-L28]...):\n"
            "  - Security lock messages (UserError/ValidationError):\n"
            "    * \"Vous n'avez pas le permission de valider cette demande d'achat.\" "
            "(condition : not (user_ok or email_ok))\n"
            "    * \"Au-dela de 10 000 euros, seule la Direction peut valider "
            "(liste restreinte).\" (condition : rec.montant_estime > 10000 and (not email_ok))\n"
        )
        answer = (
            "La regle de separation des roles ne s'applique pas si aucune "
            "demande d'achat n'est liee."
        )
        result = _backfill_missing_override_chain_amount(answer, contaminated_raw_text)
        assert result == answer, (
            "contamination regression: an unrelated model's condition text "
            "was mistaken for an override-cascade finding"
        )
        assert "chaîne de surcharge" not in result.lower()


# gap, module 1/8 (2026-08-12, 01b-technical): the marker-only
# E2E check verified the two other override modules were present SOMEWHERE
# in the final answer (via _backfill_missing_override_modules), but a live
# run showed the LLM's free prose actively denying they existed ("Aucune
# autre surcharge n'a été détectée...") and fabricating a specificity-based
# short-circuit that doesn't exist in Odoo -- see the comment above
# _OVERRIDE_COUNT_DENIAL_RE in rag/graph.py for the full live-run text.
class TestOverrideCascadeContradictionCorrection:
    def test_detects_denial_of_other_overrides(self):
        answer = (
            "1. custom_credit_note_approval. Aucune autre surcharge n'a été "
            "détectée dans les autres modules analysés."
        )
        assert _answer_denies_other_overrides(answer) is True

    def test_no_denial_detected_on_clean_answer(self):
        answer = (
            "Les 3 modules concernés sont 'custom_credit_note_approval_vip', "
            "'custom_credit_note_approval_regional' et 'custom_credit_note_approval'."
        )
        assert _answer_denies_other_overrides(answer) is False

    def test_detects_fabricated_shortcircuit_claim(self):
        answer = (
            "La surcharge la plus spécifique est exécutée en premier ; si "
            "elle ne lève pas d'erreur, les autres ne seront pas exécutées."
        )
        assert _answer_asserts_override_shortcircuit(answer) is True

    def test_no_shortcircuit_false_positive_on_unrelated_error_mention(self):
        """'erreur' appearing elsewhere in the answer, with no 'ne pas
        exécutée(s)' clause in the SAME sentence, must not trigger --
        narrow, confirmed-real vocabulary only, same discipline as
        _LINK_GUARD_CONTRADICTION_PATTERN."""
        answer = (
            "Si les données du formulaire sont invalides, Odoo lève une "
            "erreur de validation avant l'enregistrement."
        )
        assert _answer_asserts_override_shortcircuit(answer) is False

    def test_neutralize_replaces_denial_sentence_with_real_count_and_modules(self):
        answer = (
            "1. custom_credit_note_approval, verrou de base. "
            "2. Aucune autre surcharge n'a été détectée dans les autres "
            "modules analysés."
        )
        modules = [
            "custom_credit_note_approval_vip",
            "custom_credit_note_approval_regional",
            "custom_credit_note_approval",
        ]
        result = _neutralize_override_count_denial(answer, modules)
        assert "aucune autre surcharge" not in result.lower()
        assert "3 surcharges" in result
        for m in modules:
            assert m in result

    def test_neutralize_denial_no_op_when_no_denial_present(self):
        answer = "Les 3 modules sont correctement listés ci-dessus."
        result = _neutralize_override_count_denial(answer, ["a", "b", "c"])
        assert result == answer

    def test_neutralize_replaces_shortcircuit_sentence_with_real_semantics(self):
        answer = (
            "En ce qui concerne l'ordre d'exécution, la surcharge la plus "
            "spécifique est exécutée en premier, et si elle ne lève pas "
            "d'erreur, les autres ne seront pas exécutées."
        )
        modules = [
            "custom_credit_note_approval_vip",
            "custom_credit_note_approval_regional",
            "custom_credit_note_approval",
        ]
        result = _neutralize_override_shortcircuit_sentence(answer, modules)
        assert "ne seront pas" not in result.lower()
        assert "court-circuit" in result
        assert "super()" in result
        # Real execution order restated, vip -> regional -> base.
        assert result.index("custom_credit_note_approval_vip") < result.index(
            "custom_credit_note_approval_regional"
        )

    def test_neutralize_shortcircuit_no_op_when_no_contradiction_present(self):
        answer = "Les 3 surcharges s'exécutent toutes, chacune appelant super()."
        result = _neutralize_override_shortcircuit_sentence(answer, ["a", "b", "c"])
        assert result == answer

    def test_correct_override_cascade_contradictions_end_to_end_on_real_live_case(self):
        """Reproduces the reported  live failure end to
        end: both the denial and the fabricated short-circuit claim in the
        same answer, against the real _REAL_OVERRIDE_CHAIN_RAW_TEXT
        fixture. Confirms both are corrected in a single pass and neither
        neutralization interferes with the other."""
        answer = (
            "Il existe plusieurs surcharges de la méthode "
            "action_valider_avoir : 1. custom_credit_note_approval, qui "
            "applique le verrou de base. 2. Aucune autre surcharge n'a été "
            "détectée dans les autres modules analysés. Concernant l'ordre "
            "d'exécution, la surcharge la plus spécifique est exécutée en "
            "premier ; si elle ne lève pas d'erreur, les autres ne seront "
            "pas exécutées."
        )
        result = _correct_override_cascade_contradictions(answer, _REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert "aucune autre surcharge" not in result.lower()
        assert "ne seront pas" not in result.lower()
        assert "custom_credit_note_approval_vip" in result
        assert "custom_credit_note_approval_regional" in result

    def test_no_op_on_single_module_chain_denial_is_not_a_contradiction(self):
        """A single-override method correctly saying 'no other override
        exists' is TRUE, not a contradiction -- must not be touched."""
        single_module_raw = "module 'only_one_module' -- link, no other line"
        answer = "Aucune autre surcharge n'a été détectée pour cette méthode."
        result = _correct_override_cascade_contradictions(answer, single_module_raw)
        assert result == answer

    def test_no_op_when_raw_text_has_no_override_chain_content(self):
        answer = "Aucune autre surcharge n'a été détectée."
        result = _correct_override_cascade_contradictions(answer, "rien à voir ici")
        assert result == answer


# gap (2026-08-13, check_native_odoo_out_of_scope.py on
# mrp.production): resolve_business_term() correctly returns
# is_resolved=False on a genuinely out-of-corpus native Odoo model, but
# nothing acted on that signal -- a live run showed the LLM opening by
# correctly noting the model wasn't found, then fabricating a plausible
# role-based answer from pretrained knowledge anyway, in the same answer.
class TestForceOutOfScopeModelAnswer:
    def test_fires_on_unresolved_concept_naming_a_technical_looking_model(self):
        """Real confirmed live case: mrp.production."""
        concept = SimpleNamespace(is_resolved=False)
        question = (
            "Qui peut lancer un ordre de fabrication (mrp.production) dans "
            "Odoo, sans aucune personnalisation -- juste le comportement "
            "standard ?"
        )
        result = _force_out_of_scope_model_answer(question, concept)
        assert result is not None
        assert "mrp.production" in result
        assert "pas present dans le corpus indexe" in result

    def test_no_op_when_concept_is_resolved(self):
        """Even if the question happens to also contain a dotted-looking
        token, a successfully resolved concept must never be overridden --
        this guard only fires on genuine resolver failure."""
        concept = SimpleNamespace(is_resolved=True)
        question = "Qui peut valider un avoir (account.move) de plus de 5000e ?"
        assert _force_out_of_scope_model_answer(question, concept) is None

    def test_no_op_on_unresolved_concept_with_no_technical_looking_mention(self):
        """Narrow scoping check: a generic/meta question with no dotted
        technical-looking identifier must not be forced into a false
        'model not found' decline -- see the module docstring in
        rag/graph.py for why this guard is deliberately this narrow."""
        concept = SimpleNamespace(is_resolved=False)
        question = "Comment fonctionne ce systeme en general ?"
        assert _force_out_of_scope_model_answer(question, concept) is None

    def test_no_op_on_empty_question(self):
        concept = SimpleNamespace(is_resolved=False)
        assert _force_out_of_scope_model_answer("", concept) is None


# gap, module 4/8 (custom_purchase_request, 04a-business /
# 04c-manager-trap, found 2026-08-13): analyze_security_locks's
# second, amount-gated UserError ("Au-dela de 10 000 euros, seule la
# Direction peut valider") was reliably present in the raw tool text but
# dropped from the synthesized answer -- see the module-level comment
# above _SECURITY_LOCK_MESSAGES_MARKER in rag/graph.py for the full
# diagnosis. Fixture text below mirrors analyze_python_security_locks'
# real rendering verbatim for custom_purchase_request/models/
# purchase_request.py (both exception messages + the required group
# line), and the contamination test reuses _REAL_OVERRIDE_CHAIN_RAW_TEXT
# already defined above (the reverse-direction leak, proven real by
# TestBackfillMissingOverrideChainAmount's own contamination test).
_REAL_SECURITY_LOCK_RAW_TEXT = (
    f"Analyse des verrous Python (file://{_TEST_CORE_ADDONS_PATH}/"
    "custom_purchase_request/models/purchase_request.py#L1-L28) "
    "[Confiance: high]:\n"
    "  - [SENSITIVE BYPASS] Logins/Emails privilégies en dur: "
    "['direction@societe.com', 'daf@societe.com']\n"
    "  - Security lock messages (UserError/ValidationError):\n"
    "    * \"Vous n'avez pas le permission de valider cette demande d'achat.\" "
    "(condition : not (user_ok or email_ok))\n"
    "    * \"Au-dela de 10 000 euros, seule la Direction peut valider "
    "(liste restreinte).\" (condition : rec.montant_estime > 10000 and "
    "not email_ok)\n"
    "  - Groupe(s) technique(s) requis detecte(s) (has_group): "
    "purchase.group_purchase_manager\n"
    "    * has_group('purchase.group_purchase_manager') se trouve dans "
    "la methode 'action_valider()' -- ne pas l'attribuer a une autre "
    "methode sans le verifier explicitement dans le code source.\n"
)


class TestBackfillMissingSecurityLockAmount:
    def test_extracts_amount_from_condition_text(self):
        assert _extract_security_lock_condition_amounts(_REAL_SECURITY_LOCK_RAW_TEXT) == ["10000"]

    def test_no_op_when_marker_absent(self):
        assert _extract_security_lock_condition_amounts(
            "rec.montant_estime > 10000, mais sans le marqueur attendu"
        ) == []

    def test_backfills_amount_dropped_from_business_phrased_answer(self):
        answer = (
            "Un utilisateur membre du groupe purchase.group_purchase_manager "
            "peut valider une demande d'achat de 15 000€."
        )
        result = _backfill_missing_security_lock_amount(answer, _REAL_SECURITY_LOCK_RAW_TEXT)
        assert "10000" in result
        assert "[FAIT DÉTERMINISTIQUE]" in result

    def test_no_op_when_amount_already_present_unspaced(self):
        answer = "Au-dela de 10000€, seule la Direction peut valider."
        result = _backfill_missing_security_lock_amount(answer, _REAL_SECURITY_LOCK_RAW_TEXT)
        assert result == answer

    def test_no_op_when_amount_already_present_with_space(self):
        answer = "Au-dela de 10 000€, seule la Direction peut valider."
        result = _backfill_missing_security_lock_amount(answer, _REAL_SECURITY_LOCK_RAW_TEXT)
        assert result == answer

    def test_backfills_regardless_of_question_wording(self):
        result = _backfill_missing_security_lock_amount("réponse courte", _REAL_SECURITY_LOCK_RAW_TEXT)
        assert "10000" in result

    def test_no_op_when_raw_text_has_no_marker(self):
        result = _backfill_missing_security_lock_amount("réponse courte", "rien à voir ici")
        assert result == "réponse courte"

    def test_no_op_on_unrelated_rec_comparison_outside_security_lock_text(self):
        """Reverse-direction contamination check: an override-cascade
        finding's own 'rec.amount_total > 20000' (a DIFFERENT tool's
        output, analyze_method_override_chain -- see
        _REAL_OVERRIDE_CHAIN_RAW_TEXT above) must never be mistaken for a
        security-lock condition amount just because both tools render
        Python comparisons the same way."""
        result = _extract_security_lock_condition_amounts(_REAL_OVERRIDE_CHAIN_RAW_TEXT)
        assert result == [], (
            "contamination regression: an override-cascade amount was "
            "mistaken for a security-lock condition amount"
        )

    def test_no_op_on_unrelated_amount_in_a_separate_joined_block(self):
        """ /  live failure (2026-08-13
        rerun): the previous test above only proves the override-cascade
        text is clean IN ISOLATION (no marker anywhere in it). On
        account.move, the real scoped_tool_output handed to this function
        can contain BOTH this security-lock block (marker present, real
        amount 10000/5000-shaped) AND a separate analyser_chaine_surcharge_
        methode block (no marker, its own unrelated 20000) joined with the
        same '\n\n' separator _scoped_raw_tool_output always uses -- model-
        scoping alone cannot split them apart since both target the same
        model. The old (pre-fix) implementation gated on the marker being
        present ANYWHERE in the full string, then scanned the ENTIRE
        string for amounts -- silently absorbing the unrelated 20000 into
        the security-lock backfill and mislabeling it as a 'verrou de
        securite' amount (live-confirmed:  asserted
        20000 as the security-lock threshold, and the real 5000 never
        appeared anywhere in that answer; 's backfilled
        20000 fact directly contradicted its own correct prose two lines
        above, which cited 5000). This test reproduces that exact combined
        shape and locks in per-block scoping as the fix."""
        combined = _REAL_SECURITY_LOCK_RAW_TEXT + "\n\n" + _REAL_OVERRIDE_CHAIN_RAW_TEXT
        result = _extract_security_lock_condition_amounts(combined)
        assert result == ["10000"], (
            "contamination regression: an override-cascade amount from a "
            "separate joined block leaked into the security-lock "
            f"extraction (got {result!r})"
        )


# gap, found 2026-08-13 (module 1/8, 01a-business rerun --
# AFTER the per-block scoping fix above is confirmed working on
# 01b-technical/01c-vip-trap): the real custom_credit_note_approval
# security lock (source: /home/user/odoo-17.0/addons/
# custom_credit_note_approval/models/account_move.py, 'rec.amount_total >
# 5000 and not has_group(...)') never reached 01a-business's final
# answer, even though the forced pre-dispatch of analyze_security_locks
# is unconditional (not gated on question phrasing) and fires identically
# for 01a/01b/01c. Root cause: _backfill_missing_security_lock_amount's old
# local _amount_present() did a plain `in` substring check on the spaced
# thousands-separator form ('5 000'), and 01a's own question amount gets
# echoed verbatim in the synthesized answer's opening sentence ('un avoir
# de 25 000€') -- '5 000' is a literal substring of '25 000', so the check
# false-positived and the backfill silently no-op'd, believing the fact was
# already covered. Fixed by _amount_present_in_text using a digit-boundary
# regex instead of a bare substring check.
_REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT = (
    f"Analyse des verrous Python (file://{_TEST_CORE_ADDONS_PATH}/"
    "custom_credit_note_approval/models/account_move.py#L14-L18) "
    "[Confiance: high]:\n"
    "  - Security lock messages (UserError/ValidationError):\n"
    "    * \"Seul un responsable comptable peut valider un avoir de plus "
    "de 5000€.\" (condition : rec.amount_total > 5000 and not "
    "has_group('account.group_account_manager'))\n"
    "  - Groupe(s) technique(s) requis detecte(s) (has_group): "
    "account.group_account_manager\n"
)


class TestAmountPresentInText:
    def test_spaced_amount_not_falsely_matched_inside_larger_echoed_amount(self):
        """Live bug reproduction: 's own answer echoes
        the question's amount ('un avoir de 25 000€'), which contains the
        spaced form of the unrelated real threshold ('5 000') as a bare
        substring. Must NOT count as the 5000€ security-lock fact already
        being present."""
        answer = (
            "D'après l'analyse des verrous Python, il semble que la question "
            "concerne les droits d'approuver un avoir de 25 000€ pour un "
            "client normal (pas VIP) dans le cadre de l'application Odoo."
        )
        assert _amount_present_in_text("5000", answer) is False

    def test_unspaced_amount_not_falsely_matched_inside_larger_number(self):
        assert _amount_present_in_text("5000", "le montant est de 125000 euros") is False

    def test_genuine_spaced_amount_detected(self):
        assert _amount_present_in_text("5000", "le seuil est de 5 000 euros") is True

    def test_genuine_unspaced_amount_detected(self):
        assert _amount_present_in_text("5000", "le seuil est de 5000 euros") is True

    def test_genuine_amount_with_currency_suffix_detected(self):
        assert _amount_present_in_text("5000", "un avoir de plus de 5000€.") is True


class TestBackfillSecurityLockAmountNotMaskedByEchoedQuestionAmount:
    def test_backfills_real_threshold_despite_larger_amount_echoed_in_answer_bloc9_01a(self):
        """End-to-end reproduction of the live  gap:
        the answer never states the real 5000€ threshold on its own terms,
        it only echoes the question's 25 000€ -- the backfill must still
        fire and append the real 5000€ fact."""
        answer = (
            "D'après l'analyse des verrous Python, il semble que la question "
            "concerne les droits d'approuver un avoir de 25 000€ pour un "
            "client normal (pas VIP) dans le cadre de l'application Odoo."
        )
        result = _backfill_missing_security_lock_amount(
            answer, _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT
        )
        assert "5000" in result
        assert "[FAIT DÉTERMINISTIQUE]" in result

    def test_no_op_when_real_threshold_genuinely_already_present(self):
        answer = "Seul un responsable comptable peut valider un avoir de plus de 5000€."
        result = _backfill_missing_security_lock_amount(
            answer, _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT
        )
        assert result == answer


# gap fix (2026-08-13, module 6/8, 06c-technical-condition-
# capture): fourth degenerate-decoding-collapse shape -- a snowballing
# sentence where each line restates the previous one as a prefix and
# appends a further clause, never caught by the exact-line-match detector
# since every line is technically unique.
class TestDegenerateGrowingRepetition:
    _REAL_SNOWBALL_TEXT = (
        "Il n'y a pas de restriction supplémentaire pour les avoirs dont la "
        "valeur totale est inférieure à 5000€.\n\n"
        "Il n'y a pas de restriction supplémentaire pour les avoirs qui ne "
        "sont pas validés par un responsable comptable.\n\n"
        "Il n'y a pas de restriction supplémentaire pour les avoirs qui ne "
        "sont pas associés à une facture de dépense.\n\n"
        "Il n'y a pas de restriction supplémentaire pour les avoirs qui ne "
        "sont pas associés à une facture de dépense et qui ne nécessitent "
        "pas de mise à jour de la partie commerciale.\n\n"
        "Il n'y a pas de restriction supplémentaire pour les avoirs qui ne "
        "sont pas validés par un responsable comptable et qui ne sont pas "
        "associés à une facture de dépense et qui ne nécessitent pas de "
        "mise à jour de la partie commerciale.\n"
    )

    def test_detects_real_snowballing_sentence_bloc9_06c(self):
        assert _detect_degenerate_growing_repetition(self._REAL_SNOWBALL_TEXT) is True

    def test_no_false_positive_on_four_distinct_fait_deterministique_lines(self):
        legit = (
            "[FAIT DÉTERMINISTIQUE] Groupe(s) technique(s) requis (has_group) "
            "détecté(s) dans le code pour cette action : account.group_account_manager.\n\n"
            "[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut "
            "également le/les module(s) suivant(s) : 'hr_expense'.\n\n"
            "[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne "
            "de surcharge : module 'hr_expense'.\n\n"
            "[FAIT DÉTERMINISTIQUE] Le verrou de sécurité contient une condition "
            "supplémentaire déclenchée au-delà de 5000€.\n"
        )
        assert _detect_degenerate_growing_repetition(legit) is False

    def test_no_op_on_normal_short_answer(self):
        normal = "Seul un responsable comptable peut valider un avoir de plus de 5000€."
        assert _detect_degenerate_growing_repetition(normal) is False

    def test_strip_collapses_snowball_to_first_occurrence_per_prefix_group(self):
        stripped = _strip_degenerate_growing_repetition(self._REAL_SNOWBALL_TEXT)
        assert _detect_degenerate_growing_repetition(stripped) is False
        # the shortest (first) line of the shared-prefix group survives
        assert "qui ne sont pas validés par un responsable comptable." in stripped


# gap, module 6/8 (06c-technical-condition-capture, found
# 2026-08-13 -- rerun immediately after the analyze_server_actions
# truncation-cap fix and the degenerate-growing-repetition detector above
# are both confirmed active on disk, pytest 66/66 green): 06b/06c both
# regained 'in_refund', but 06c still dropped the hardcoded privileged-
# partner IDs (42, 108, 231) -- present verbatim in the raw tool text
# (confirmed by the check script's own raw check, which shows 'IDs en
# dur' present under the now-3000 cap) but paraphrased away by synthesis.
# Fixture text below mirrors analyze_server_actions's real rendering
# verbatim for custom_automation_traps' ir.actions.server bypass finding
# on account.move (same finding block pasted live by the user), including
# the preceding boilerplate 'Aucun pattern de securite detecte' entries
# that motivated the cap raise, to catch any future regression where the
# marker line is scanned globally instead of per-finding.
_REAL_SERVER_ACTION_RAW_TEXT = (
    "Analyse du code de l'action serveur 'account.invoice_send' "
    "[Confiance: FAIBLE - logique en données XML, modifiable à "
    "l'exécution]:\n"
    "  - Aucun pattern de sécurité détecté dans le code.\n\n"
    "Analyse du code de l'action serveur "
    "'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' "
    "[Confiance: FAIBLE - logique en données XML, modifiable à "
    "l'exécution]:\n"
    "  - [SENSITIVE BYPASS] SUDO détecté: Contournement des droits "
    "d'accès via sudo()\n"
    "  - [SENSITIVE BYPASS] IDs en dur: [42, 108, 231] → traitement "
    "privilégié non documenté\n"
    "  - Condition(s) de déclenchement: rec.move_type == 'in_refund' and "
    "rec.partner_id.id in FOURNISSEURS_PRIVILEGIES\n"
)


class TestBackfillMissingHardcodedIds:
    def test_extracts_all_three_ids_in_order(self):
        assert _extract_hardcoded_id_literals(_REAL_SERVER_ACTION_RAW_TEXT) == [
            "42", "108", "231",
        ]

    def test_no_op_when_marker_absent(self):
        assert _extract_hardcoded_id_literals(
            "Aucun pattern de sécurité détecté dans le code."
        ) == []

    def test_backfills_ids_dropped_from_technical_answer_bloc9_06c(self):
        """Live  failure: 'in_refund'
        is correctly present (trigger-condition backfill above already
        covers it) but none of the three hardcoded IDs ever appear."""
        answer = (
            "La condition rec.move_type == 'in_refund' est déclenchée "
            "lorsque l'action serveur automatise la validation d'avoirs "
            "reçus de trois fournisseurs spécifiques, en contournant les "
            "règles d'accès et les ACL via sudo()."
        )
        result = _backfill_missing_hardcoded_id_literals(answer, _REAL_SERVER_ACTION_RAW_TEXT)
        for expected_id in ("42", "108", "231"):
            assert _amount_present_in_text(expected_id, result)
        assert "[FAIT DÉTERMINISTIQUE]" in result

    def test_no_op_when_all_ids_already_present(self):
        answer = (
            "Les identifiants concernés sont 42, 108 et 231, traités via "
            "sudo() sans passer par les règles d'approbation habituelles."
        )
        result = _backfill_missing_hardcoded_id_literals(answer, _REAL_SERVER_ACTION_RAW_TEXT)
        assert result == answer

    def test_does_not_false_positive_on_id_as_substring_of_larger_number(self):
        """Digit-boundary check (via _amount_present_in_text, same as the
        monetary-amount backfills): '42' must not be considered already
        present merely because '142' or '420' appears in the answer."""
        answer = (
            "La condition rec.move_type == 'in_refund' concerne un montant "
            "de 142 euros pour le fournisseur 420."
        )
        result = _backfill_missing_hardcoded_id_literals(answer, _REAL_SERVER_ACTION_RAW_TEXT)
        assert "[FAIT DÉTERMINISTIQUE]" in result
        for expected_id in ("42", "108", "231"):
            assert _amount_present_in_text(expected_id, result)

    def test_no_op_when_raw_text_has_no_hardcoded_id_finding(self):
        result = _backfill_missing_hardcoded_id_literals(
            "réponse courte",
            "Analyse du code de l'action serveur 'account.invoice_send': "
            "Aucun pattern de sécurité détecté dans le code.",
        )
        assert result == "réponse courte"

    def test_gated_out_finding_for_anonymous_requester_yields_no_backfill(self):
        """ gating: an anonymous requester's observation has
        already had the 'IDs en dur' line redacted by authorization_gate.py
        before this backfill ever sees it (see the module-level comment
        above _HARDCODED_IDS_LINE_RE in rag/graph.py) -- confirms this
        backfill cannot leak gated content back in, since it only ever
        reads from the already-gated scoped_tool_output."""
        gated_text = (
            "Analyse du code de l'action serveur "
            "'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie':\n"
            "  \U0001F512 ELEMENT OMITTED FOR AUTHORIZATION REASON : cette ligne décrit un "
            "mécanisme de contournement de sécurité.\n"
            "  - Condition(s) de déclenchement: rec.move_type == 'in_refund' and "
            "rec.partner_id.id in FOURNISSEURS_PRIVILEGIES\n"
        )
        result = _backfill_missing_hardcoded_id_literals("réponse", gated_text)
        assert result == "réponse"


class TestQuestionIsAccessRelated:
    """ gap, 2026-08-13 (native-Odoo-out-of-scope investigation --
    'qui peut confirmer un devis (sale.order)' returned a thin, uncited
    answer because who_has_access_to had no forced pre-dispatch at all):
    locks in the question-shape pattern that now forces who_has_access_to --
    see _ACCESS_QUESTION_PATTERN in rag/graph.py for the full rationale
    (an open-ended business-verb keyword list doesn't generalize across
    modules the way it does for approval questions, and a structural
    guard doesn't make sense for ACL since virtually every real model
    has entries -- the question shape itself is the meaningful filter)."""

    def test_matches_qui_peut(self):
        assert _question_is_access_related(
            "Qui peut confirmer un devis (sale.order) en bon de commande ?"
        )

    def test_matches_qui_a_le_droit(self):
        assert _question_is_access_related(
            "Qui a le permission d'approuver un avoir de 25 000€ ?"
        )

    def test_matches_qui_est_autorise(self):
        assert _question_is_access_related(
            "Qui est autorisé à valider une demande de congé ?"
        )

    def test_matches_english_who_can(self):
        assert _question_is_access_related("Who can confirm this sales order?")

    def test_does_not_match_unrelated_technical_question(self):
        assert not _question_is_access_related(
            "Quelles sont les conditions vérifiées par action_valider_avoir ?"
        )

    def test_does_not_match_bare_qui_without_capability_verb(self):
        """'qui' alone (e.g. asking about a person/owner field) is not an
        access question -- must not over-match on the bare pronoun."""
        assert not _question_is_access_related(
            "Qui est le créateur de cet enregistrement ?"
        )

    # 08c gap (2026-08-14): "peut-il/elle voir" forms were not matched
    # by the original pattern, which only recognized "qui peut/a le permission".
    def test_matches_peut_il_voir_bloc9_08c(self):
        """The exact 08c question shape that wasn't matched."""
        assert _question_is_access_related(
            "Un utilisateur standard peut-il voir un document de 30 000€ ?"
        )

    def test_matches_peut_elle_acceder(self):
        assert _question_is_access_related(
            "La comptable peut-elle accéder aux factures fournisseur ?"
        )

    def test_matches_a_t_il_le_droit(self):
        assert _question_is_access_related(
            "L'employé a-t-il le permission de consulter ce document ?"
        )

    def test_matches_english_can_a_user_see(self):
        assert _question_is_access_related(
            "Can a user see this record if the company differs?"
        )

    def test_does_not_match_comment_configurer(self):
        assert not _question_is_access_related(
            "Comment configurer un module Odoo pour la comptabilité ?"
        )


# 08c follow-up, requested 2026-08-13: _extract_company_context, see
# rag/graph.py's own module-level comment above the function for why this
# is qualitative same/different only, never a resolved id/name.
class TestExtractCompanyContext:
    def test_same_company_explicit(self):
        result = _extract_company_context(
            "Un utilisateur de la même société peut-il voir ce document ?"
        )
        assert result == {"company_id": 1, "user": {"company_id": {"id": 1}}, "company_ids": [1]}

    def test_same_filiale_explicit(self):
        result = _extract_company_context(
            "Un utilisateur de la même filiale peut-il valider ce document ?"
        )
        assert result == {"company_id": 1, "user": {"company_id": {"id": 1}}, "company_ids": [1]}

    def test_different_company_adjective_before_noun(self):
        result = _extract_company_context(
            "Un utilisateur d'une autre société peut-il voir ce document ?"
        )
        assert result == {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}

    def test_different_company_adjective_after_noun(self):
        """French allows both word orders ('autre société' and 'société
        différente') -- both must resolve to DIFFERENT. The first regex
        draft only handled the adjective-before-noun order and silently
        returned {} on this phrasing; caught by a sandbox functional check
        before this test was even written, not by running pytest."""
        result = _extract_company_context(
            "Un utilisateur d'une société différente peut-il voir ce document ?"
        )
        assert result == {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}

    def test_different_filiale_and_entreprise_synonyms(self):
        assert _extract_company_context(
            "Un utilisateur d'une filiale différente peut-il valider ce document ?"
        ) == {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}
        assert _extract_company_context(
            "Un utilisateur d'une entreprise différente peut-il valider ce document ?"
        ) == {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}

    def test_negation_precedence_over_same(self):
        """'pas la même société' contains 'même société' as a literal
        substring -- must resolve to DIFFERENT, never SAME."""
        result = _extract_company_context(
            "Un utilisateur qui n'est pas de la même société peut-il voir ce document ?"
        )
        assert result == {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}

    def test_no_company_mention_returns_empty_dict(self):
        """Q6.1-style question (): no company wording
        at all -- must return {}, not a guessed same/different, so
        can_view_amount_v2's company_id leaf still resolves to the same
        honest None (\"cannot conclude\") it did before this follow-up."""
        result = _extract_company_context(
            "Un utilisateur membre à la fois du groupe régional et du groupe "
            "national peut-il voir un avoir de 80 000€ ?"
        )
        assert result == {}

    def test_case_insensitive(self):
        result = _extract_company_context(
            "UN UTILISATEUR D'UNE AUTRE SOCIÉTÉ PEUT-IL VOIR CE DOCUMENT ?"
        )
        assert result == {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}

    def test_different_with_copula_est_between_noun_and_adjective_bloc9_08c(self):
        """Live bug, found 2026-08-13 ( rerun,
        AFTER _extract_company_context/can_view_amount_v2 wiring already
        landed and passed its own 27-test suite): the noun-adjective
        adjacency the previous regex assumed ('entreprise différente')
        does not hold for this question's real phrasing, which has a
        copula in between ('l'entreprise **est** différente de celle du
        document') -- the regex silently matched nothing, so
        can_view_amount_v2 never got a company context and the whole fix
        never actually reached this question despite passing every other
        test. Reproduced verbatim against the real question text before
        fixing the regex."""
        result = _extract_company_context(
            "Un utilisateur standard (groupe de base uniquement) dont "
            "l'entreprise est différente de celle du document peut-il voir "
            "un document de 30 000€ appartenant à un autre utilisateur, "
            "sachant que 30 000€ est sous le seuil de 50 000€ ?"
        )
        assert result == {"company_id": 1, "user": {"company_id": {"id": 2}}, "company_ids": [2]}

    def test_double_negation_est_pas_differente_stays_unresolved(self):
        """'n'est pas différente' is a double negative meaning SAME, but
        this narrow qualitative extractor makes no attempt to parse
        negation-of-negation -- per Regle 5 (rules.md), an ambiguous/
        unhandled phrasing must resolve to {} (unresolved), never a
        guessed value in either direction. Locks in that the copula fix
        above does not accidentally start guessing DIFFERENT here just
        because 'est' now precedes 'différente'."""
        result = _extract_company_context(
            "Un utilisateur dont l'entreprise n'est pas différente de celle "
            "du document peut-il voir ce document ?"
        )
        assert result == {}


# Bug B2 fix, section 3/4 (2026-08-21,  section 101/102):
# company_ids must mirror the CURRENT USER's own company (user.company_id.id),
# never the top-level company_id key (the RECORD's placeholder) -- these are
# semantically different things a bare vs. dotted dynamic ref resolves to in
# real Odoo's ir.rule evaluation context. Locks in the exact value, not just
# the key's presence, so a future edit can't silently swap company_id back in.
class TestExtractCompanyContextCompanyIdsSemantics:
    def test_same_company_populates_company_ids_from_user_not_record(self):
        result = _extract_company_context(
            "Un utilisateur de la même société peut-il voir ce document ?"
        )
        assert result["company_ids"] == [1]
        assert result["company_ids"] == [result["user"]["company_id"]["id"]]

    def test_different_company_populates_company_ids_from_user_not_record(self):
        """The regression this test guards against: company_ids = [company_id]
        (the record's placeholder, always 1 here) would give [1] for this
        case -- wrong, since the user's own company is 2, not 1. Only
        [user.company_id.id] == [2] is semantically correct for a bare
        company_ids dynamic ref (real Odoo: self.env.companies.ids, the
        CURRENT USER's accessible companies, never the record being tested)."""
        result = _extract_company_context(
            "Un utilisateur d'une autre société peut-il voir ce document ?"
        )
        assert result["company_ids"] == [2]
        assert result["company_ids"] == [result["user"]["company_id"]["id"]]
        assert result["company_ids"] != [result["company_id"]]

    def test_no_company_mention_has_no_company_ids_key(self):
        assert "company_ids" not in _extract_company_context(
            "Qui peut approuver un avoir de 25 000€ ?"
        )

    def test_resolves_real_miro_ai_bare_company_ids_domain_force_same_company(self):
        """Integration-level lock, not just a dict-shape check: reproduces
        the exact domain_force that motivated this fix (miro_ai/security/
        miro_ai_security.xml::rule_miro_ai_settings_company) --
        ('company_id', 'in', company_ids) -- via the real deterministic
        evaluator, not a mock. Before this fix, 'company_ids' was never a
        context key at all -- an unresolved dynamic ref, verdict always
        None regardless of company wording, even when the question was
        maximally explicit about company (the exact section 101 symptom)."""
        from code_intelligence.knowledge_rules.deterministic.access.domain_evaluator import evaluate_domain_force
        context = {"amount": 1000}
        context.update(_extract_company_context(
            "Un utilisateur de la même société peut-il voir ce paramètre ?"
        ))
        verdict, unresolved = evaluate_domain_force(
            "[('company_id', 'in', company_ids)]", context
        )
        assert verdict is True
        assert unresolved == []

    def test_resolves_real_miro_ai_bare_company_ids_domain_force_different_company(self):
        from code_intelligence.knowledge_rules.deterministic.access.domain_evaluator import evaluate_domain_force
        context = {"amount": 1000}
        context.update(_extract_company_context(
            "Un utilisateur d'une autre société peut-il voir ce paramètre ?"
        ))
        verdict, unresolved = evaluate_domain_force(
            "[('company_id', 'in', company_ids)]", context
        )
        assert verdict is False
        assert unresolved == []

    def test_no_company_mention_leaves_bare_company_ids_domain_force_unresolved(self):
        """No regression on the silent-mention case : absence of information must still
        resolve to None ('cannot conclude'), never a guessed True/False."""
        from code_intelligence.knowledge_rules.deterministic.access.domain_evaluator import evaluate_domain_force
        context = {"amount": 1000}
        context.update(_extract_company_context(
            "Qui peut approuver un avoir de 25 000€ ?"
        ))
        verdict, unresolved = evaluate_domain_force(
            "[('company_id', 'in', company_ids)]", context
        )
        assert verdict is None
        assert "company_ids" in unresolved


# Bug B2 fix, section 2 continued (2026-08-21,  section
# 101/102): the context dict built at both ci_agent_node.py call sites must
# carry BOTH "amount" and "amount_total" (same value), never a rename --
# the real corpus has domain_force leaves on both field names for
# genuinely distinct models (account.move.amount_total vs.
# custom.deep.document.amount, a real Float field, not a typo -- see
# custom_deep_inheritance_security/security/security_rules.xml). These
# tests exercise the real evaluator directly against both actual
# domain_force strings, not just a context dict's shape, so a future edit
# that reverts to a single key would be caught here even if it happened to
# preserve the dict's other keys.
class TestAmountContextDualKey:
    def test_amount_total_leaf_resolves_true_when_amount_key_present(self):
        """custom_credit_note_visibility_rules::rule_avoir_visibilite_regionale
        -- references amount_total, not amount."""
        from code_intelligence.knowledge_rules.deterministic.access.domain_evaluator import evaluate_domain_force
        context = {"amount": 30000, "amount_total": 30000}
        verdict, unresolved = evaluate_domain_force(
            "['|', ('move_type', '!=', 'out_refund'), ('amount_total', '<=', 50000)]",
            context,
        )
        assert verdict is True
        assert unresolved == []

    def test_bare_amount_leaf_resolves_true_when_amount_total_key_also_present(self):
        """custom_deep_inheritance_security::rule_deep_document_complex_nested
        -- references amount (bare), a genuinely distinct real Float field
        on custom.deep.document, not amount_total. This is the exact case a
        pure rename from 'amount' to 'amount_total' would have broken."""
        from code_intelligence.knowledge_rules.deterministic.access.domain_evaluator import evaluate_domain_force
        context = {"amount": 30000, "amount_total": 30000, "user": {"id": 7}, "company_id": 1}
        verdict, unresolved = evaluate_domain_force(
            "['&', '|', ('amount', '<=', 50000), ('user_id', '=', user.id), "
            "('company_id', '=', user.company_id.id)]",
            context,
        )
        # user_id leaf unresolved (no 'user_id' key, only 'user'/'id') and
        # company_id leaf unresolved (no user.company_id.id in this
        # context) -- both OR-ed with the amount leaf under the '&' with
        # company_id, so the overall verdict is what matters here: the
        # amount leaf itself must resolve, not be swallowed as an unknown
        # field the way a rename would have left it.
        assert "amount" not in unresolved


# gap, module 8/8 (2026-08-13, follow-up investigation): grounding
# validator for group xmlids the LLM mentions in final_answer -- see the
# module-level docstring above _flag_ungrounded_group_xmlids in
# rag/graph.py for the full design rationale (flag, never strip; no-op on
# an empty grounded set). Fixture below mirrors
# analyze_python_security_locks' real rendering verbatim for
# custom_deep_inheritance_security/models/deep_document.py (re-read
# directly on disk, /home/user/odoo-17.0/addons/
# custom_deep_inheritance_security/models/deep_document.py) -- both
# has_group() checks (50k-tier account.group_account_manager in
# action_validate_level2, 100k-tier base.group_system in
# action_final_approve) live in the SAME file, so analyze_python_security_
# locks aggregates both into a single 'Groupe(s) technique(s) requis'
# summary line. This is the confirmed root cause of the 08a-business
# checker-script false positive the user diagnosed (base.group_system is
# genuinely grounded -- present in this turn's scoped_tool_output -- just
# attributed to a different threshold than the one asked about; this
# validator deliberately does not attempt to distinguish that from a
# correctly-attributed mention, per its own docstring).
_REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT = (
    f"Analyse des verrous Python (file://{_TEST_CORE_ADDONS_PATH}/"
    "custom_deep_inheritance_security/models/deep_document.py#L1-L56) "
    "[Confiance: high]:\n"
    "  - Security lock messages (UserError/ValidationError):\n"
    "    * \"Seul un responsable comptabilité peut valider au-delà de "
    "50 000€.\" (condition : rec.amount > 50000 and not "
    "self.env.user.has_group('account.group_account_manager'))\n"
    "    * \"Approbation finale > 100k€ réservée à l'administrateur "
    "système.\" (condition : rec.amount > 100000 and not "
    "self.env.user.has_group('base.group_system'))\n"
    "  - Groupe(s) technique(s) requis detecte(s) (has_group): "
    "account.group_account_manager, base.group_system\n"
    "    * has_group('account.group_account_manager') se trouve dans "
    "la methode 'action_validate_level2()' -- ne pas l'attribuer a une "
    "autre methode sans le verifier explicitement dans le code source.\n"
    "    * has_group('base.group_system') se trouve dans la methode "
    "'action_final_approve()' -- ne pas l'attribuer a une autre methode "
    "sans le verifier explicitement dans le code source.\n"
)


class TestExtractRequiredGroups:
    def test_extracts_all_groups_from_shared_has_group_summary_line(self):
        """ false-positive root cause (see the fixture's own
        module-level comment above): both methods' groups live on the same
        summary line because they share a file, so both come out as
        'required' even though only one applies to a 60 000€ question."""
        assert _extract_required_groups(_REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT) == [
            "account.group_account_manager", "base.group_system",
        ]

    def test_no_op_when_no_has_group_summary_line_present(self):
        assert _extract_required_groups("rien à voir ici") == []

    def test_dedups_and_strips_whitespace_on_comma_separated_list(self):
        raw = (
            "Groupe(s) technique(s) requis detecte(s) (has_group): "
            "a.group_x,  a.group_x , a.group_y\n"
        )
        assert _extract_required_groups(raw) == ["a.group_x", "a.group_y"]


class TestFlagUngroundedGroupXmlids:
    """ gap fix (2026-08-13, module 8/8 follow-up investigation) --
    negative/grounding validator, mirror image of _backfill_missing_
    required_groups (which only ever adds a fact already known to be
    true). See rag/graph.py's own docstring above
    _flag_ungrounded_group_xmlids for the design rationale (flag, never
    strip; no-op on an empty grounded set)."""

    def test_flags_group_xmlid_with_no_has_group_backing_anywhere(self):
        """Genuine hallucination case: 'sale.group_manager' appears nowhere
        in the raw tool output at all, under any threshold or method --
        the exact class of error this validator exists to catch."""
        answer = (
            "Un utilisateur membre du groupe sale.group_manager peut "
            "valider ce document au-delà de 60 000€."
        )
        result = _flag_ungrounded_group_xmlids(answer, _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT)
        assert "GROUPE(S) NON VÉRIFIÉ(S)" in result
        assert "sale.group_manager" in result
        # Original prose preserved verbatim -- flagged, never edited/removed.
        assert answer in result

    def test_no_op_when_mentioned_group_is_grounded(self):
        answer = "Seul un membre du groupe account.group_account_manager peut valider."
        result = _flag_ungrounded_group_xmlids(answer, _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT)
        assert result == answer

    def test_no_op_when_grounded_set_is_empty(self):
        """No has_group() line fired this turn at all -- nothing to check
        against, so even a group-shaped token in the answer must not be
        flagged (see docstring: flagging every mention in this case would
        be strictly worse than saying nothing)."""
        answer = "Un utilisateur du groupe base.group_system peut valider."
        result = _flag_ungrounded_group_xmlids(answer, "rien à voir ici")
        assert result == answer

    def test_bloc9_08a_scenario_not_flagged_grounded_but_misattributed(self):
        """The  checker-script false positive the user
        diagnosed this turn: base.group_system belongs to the 100k-tier
        method (action_final_approve), not the 60k-tier one actually asked
        about -- but it IS genuinely present in this turn's has_group()
        summary line (both methods' checks live in the same file), so this
        validator correctly leaves it alone. Distinguishing 'grounded but
        misattributed to the wrong threshold' from 'grounded and correctly
        attributed' is a different, harder problem, explicitly out of
        scope for this validator (see its docstring) -- this test locks in
        that this validator does NOT (and should not) touch ."""
        answer = (
            "Pour un montant de 60 000€, il faut que l'utilisateur soit "
            "membre du groupe account.group_account_manager. Le groupe "
            "base.group_system est également mentionné dans le code pour "
            "le palier à 100 000€."
        )
        result = _flag_ungrounded_group_xmlids(
            answer, _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT
        )
        assert result == answer

    def test_mixed_grounded_and_ungrounded_only_flags_the_ungrounded_one(self):
        answer = (
            "Le groupe purchase.group_purchase_manager est requis, ainsi "
            "que base.group_system."
        )
        result = _flag_ungrounded_group_xmlids(answer, _REAL_SECURITY_LOCK_RAW_TEXT)
        assert "base.group_system" in result
        # The flagged list must not also name the genuinely grounded group.
        warning_start = result.index("GROUPE(S) NON VÉRIFIÉ(S)")
        assert "purchase.group_purchase_manager" not in result[warning_start:]

    def test_never_strips_or_edits_original_answer_text(self):
        answer = "Un utilisateur du groupe crm.group_use_lead peut y accéder."
        result = _flag_ungrounded_group_xmlids(answer, _REAL_SECURITY_LOCK_RAW_TEXT)
        assert result.startswith(answer)


class TestExtractRequiredGroupsForAmount:
    """ gap fix (2026-08-14, module 8/8, ):
    tests that required groups extracted from security lock conditions
    are filtered by monetary threshold when an explicit amount is present."""

    def test_unfiltered_when_amount_none(self):
        groups = _extract_required_groups_for_amount(_REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT, None)
        assert groups == ["account.group_account_manager", "base.group_system"]

    def test_filters_out_higher_threshold_bloc9_08a(self):
        # 60 000€ is > 50 000€ (account.group_account_manager) but <= 100 000€ (base.group_system)
        groups = _extract_required_groups_for_amount(_REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT, 60000)
        assert groups == ["account.group_account_manager"]

    def test_includes_both_when_above_all_thresholds(self):
        groups = _extract_required_groups_for_amount(_REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT, 120000)
        assert groups == ["account.group_account_manager", "base.group_system"]

    def test_returns_empty_when_below_all_thresholds(self):
        groups = _extract_required_groups_for_amount(_REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT, 30000)
        assert groups == []

    def test_backfill_only_injects_triggered_group_for_60k(self):
        question = "Qui a le permission de valider un document à 60 000€ dans le modèle custom.deep.document ?"
        synthesized_without_groups = "Pour valider un document à 60 000€, il faut être responsable comptabilité."
        result = _backfill_missing_required_groups(synthesized_without_groups, _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT, question)
        assert "account.group_account_manager" in result
        assert "base.group_system" not in result


# gap fix (2026-08-14, module 1/8 follow-up, 'account.group_account_invoice
# noise', see  -- left deliberately open at the time as
# cosmetic, 'necessiterait un scoping fichier/module plus fin qu'un scoping
# par modele'). Real block for Odoo's own core account/models/account_move.py
# (_post(), line ~3941 on this disk), aggregated alongside the custom
# override block by analyze_security_locks on the shared account.move
# model -- confirmed by direct read of
# /home/user/odoo-17.0/addons/account/models/account_move.py.
_REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT = (
    f"Analyse des verrous Python (file://{_TEST_CORE_ADDONS_PATH}/"
    "account/models/account_move.py#L1-L5238) "
    "[Confiance: high]:\n"
    "  - Groupe(s) technique(s) requis detecte(s) (has_group): "
    "account.group_account_manager, account.group_account_invoice\n"
    "    * has_group('account.group_account_manager') se trouve dans "
    "la methode '_hash_moves()' -- ne pas l'attribuer a une autre "
    "methode sans le verifier explicitement dans le code source.\n"
    "    * has_group('account.group_account_invoice') se trouve dans "
    "la methode '_post()' -- ne pas l'attribuer a une autre methode "
    "sans le verifier explicitement dans le code source.\n"
)


class TestBlockIsCustomModuleFile:
    def test_custom_module_file_link_is_kept(self):
        assert _block_is_custom_module_file(_REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT) is True

    def test_core_odoo_file_link_is_excluded(self):
        assert _block_is_custom_module_file(_REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT) is False

    def test_block_with_no_file_link_is_kept_by_default(self):
        """Never silently drop a block this cannot positively classify as
        core/OCA Odoo -- same conservative default as every other scoping
        guard in rag/graph.py (_scoped_raw_tool_output, etc.)."""
        assert _block_is_custom_module_file("Aucun lien fichier ici.") is True


class TestRestrictBlocksToCustomModules:
    """Live reproduction of the  noise: on a shared
    model like account.move, analyze_security_locks's raw output
    contains both the real custom override block AND Odoo's own core
    block, joined with '\\n\\n' (same separator _scoped_raw_tool_output
    already relies on)."""

    def test_drops_core_odoo_block_keeps_custom_block(self):
        combined = (
            _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT
            + "\n\n"
            + _REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT
        )
        scoped = _restrict_blocks_to_custom_modules(combined)
        assert "custom_credit_note_approval" in scoped
        assert "account/models/account_move.py" not in scoped

    def test_order_independent(self):
        combined = (
            _REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT
            + "\n\n"
            + _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT
        )
        scoped = _restrict_blocks_to_custom_modules(combined)
        assert "custom_credit_note_approval" in scoped
        assert "account/models/account_move.py" not in scoped

    def test_falls_back_to_unscoped_when_no_custom_block_present(self):
        """Never drop everything: a turn with only core-Odoo blocks (no
        custom module resolved at all) keeps its original, unscoped text
        rather than losing all content."""
        scoped = _restrict_blocks_to_custom_modules(_REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT)
        assert scoped == _REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT

    def test_does_not_affect_deep_inheritance_security_fixture(self):
        """Non-regression: the existing  fixture already lives
        under a custom_* addon, so this new filter must be a no-op on it."""
        scoped = _restrict_blocks_to_custom_modules(_REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT)
        assert scoped == _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT


class TestBackfillMissingRequiredGroupsExcludesCoreOdooNoise:
    """End-to-end reproduction of the live  gap
    (account.group_account_invoice noise): _backfill_missing_required_
    groups must never inject a core-Odoo has_group() check that has
    nothing to do with the custom approval mechanism the question is
    actually about."""

    def test_backfill_never_injects_core_odoo_group_noise(self):
        question = "Qui a le permission d'approuver un avoir de 25 000€ pour un client normal ?"
        answer_missing_both = "D'après l'analyse, il faut un rôle comptable spécifique pour valider."
        combined = (
            _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT
            + "\n\n"
            + _REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT
        )
        result = _backfill_missing_required_groups(answer_missing_both, combined, question)
        assert "account.group_account_manager" in result
        assert "account.group_account_invoice" not in result

    def test_backfill_still_works_when_only_custom_block_present(self):
        """Non-regression: the fix must not break the ordinary case where
        the raw tool output never had a core-Odoo block to begin with."""
        question = "Qui a le permission d'approuver un avoir de 25 000€ pour un client normal ?"
        answer_missing_group = "D'après l'analyse, il faut un rôle comptable spécifique pour valider."
        result = _backfill_missing_required_groups(
            answer_missing_group, _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT, question
        )
        assert "account.group_account_manager" in result


# gap fix (2026-08-14, module 1/8 follow-up, LLM free-prose
# 'account.group_account_invoice' noise -- see  and
#  section 42/addendum). Live reproduction: 01a-business's
# own answer, verbatim, listed both groups as required bullets even though
# only account.group_account_manager belongs to the custom mechanism.
_REAL_01A_BULLET_ANSWER_WITH_CORE_NOISE = (
    "Il est donc recommandé de vérifier explicitement:\n"
    "- Être membre du groupe `account.group_account_manager`\n"
    "- Être membre du groupe `account.group_account_invoice`\n"
)


class TestGroundedCoreOnlyGroups:
    """See rag/graph.py's own docstring above _grounded_core_only_groups
    for the design rationale -- a third category, orthogonal to
    _flag_ungrounded_group_xmlids' grounded/ungrounded split: a group can
    be genuinely grounded (real has_group() call) while living only in a
    non-custom (core Odoo) block of the same scoped_tool_output."""

    def _combined(self):
        return (
            _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT
            + "\n\n"
            + _REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT
        )

    def test_identifies_core_only_group_mentioned_in_answer(self):
        result = _grounded_core_only_groups(
            _REAL_01A_BULLET_ANSWER_WITH_CORE_NOISE, self._combined()
        )
        assert result == ["account.group_account_invoice"]

    def test_does_not_flag_the_custom_group_even_though_also_in_core_block(self):
        """account.group_account_manager appears in BOTH blocks (real, per
        the core fixture's own has_group() summary line) -- must stay out
        of the core-only set since it is also genuinely custom-grounded."""
        result = _grounded_core_only_groups(
            _REAL_01A_BULLET_ANSWER_WITH_CORE_NOISE, self._combined()
        )
        assert "account.group_account_manager" not in result

    def test_empty_when_no_core_block_present(self):
        result = _grounded_core_only_groups(
            _REAL_01A_BULLET_ANSWER_WITH_CORE_NOISE,
            _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT,
        )
        assert result == []

    def test_empty_when_grounded_set_is_empty(self):
        answer = "Un utilisateur du groupe account.group_account_invoice peut valider."
        result = _grounded_core_only_groups(answer, "rien à voir ici")
        assert result == []

    def test_empty_when_core_group_never_mentioned_in_answer(self):
        """The core block is present in scoped_tool_output, but the answer
        itself never names the core-only group -- nothing to identify."""
        answer = "Seul un membre du groupe account.group_account_manager peut valider."
        result = _grounded_core_only_groups(answer, self._combined())
        assert result == []

    def test_bloc9_08a_scenario_not_flagged(self):
        """Non-regression: base.group_system in the deep-inheritance
        fixture lives in the SAME custom file as account.group_account_manager
        (single-file module), so it must never be classified as
        core-only -- a different, harder 'grounded but misattributed to
        the wrong threshold' problem, explicitly out of scope here (see
        _flag_ungrounded_group_xmlids' own equivalent non-regression test)."""
        answer = (
            "Pour un montant de 60 000€, il faut que l'utilisateur soit "
            "membre du groupe account.group_account_manager. Le groupe "
            "base.group_system est également mentionné dans le code pour "
            "le palier à 100 000€."
        )
        result = _grounded_core_only_groups(answer, _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT)
        assert result == []


class TestStripCoreOnlyGroupMentions:
    """See rag/graph.py's own docstring above _strip_core_only_group_mentions
    for the design rationale (in-place removal, not a flag -- precedent:
    module 5/8 Bug 2, a bandeau alone left the wrong content visible and
    readable underneath the warning)."""

    def _combined(self):
        return (
            _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT
            + "\n\n"
            + _REAL_CORE_ACCOUNT_MOVE_SECURITY_LOCK_RAW_TEXT
        )

    def test_strips_core_only_bullet_live_reproduction(self):
        """Live reproduction of the  answer verbatim."""
        result = _strip_core_only_group_mentions(
            _REAL_01A_BULLET_ANSWER_WITH_CORE_NOISE, self._combined()
        )
        assert "account.group_account_invoice" not in result
        assert "account.group_account_manager" in result

    def test_strips_inline_clause_without_touching_surrounding_sentences(self):
        answer = (
            "Seul un responsable comptable peut valider, membre du groupe "
            "account.group_account_manager. Le groupe account.group_account_invoice "
            "est également mentionné dans le fichier core. Fin de la réponse."
        )
        result = _strip_core_only_group_mentions(answer, self._combined())
        assert "account.group_account_invoice" not in result
        assert "account.group_account_manager" in result
        assert "Fin de la réponse." in result

    def test_no_op_when_only_custom_group_mentioned(self):
        answer = "Seul un membre du groupe account.group_account_manager peut valider."
        result = _strip_core_only_group_mentions(answer, self._combined())
        assert result == answer

    def test_no_op_when_grounded_set_is_empty(self):
        answer = "Un utilisateur du groupe account.group_account_invoice peut valider."
        result = _strip_core_only_group_mentions(answer, "rien à voir ici")
        assert result == answer

    def test_no_op_when_no_core_block_present(self):
        """Non-regression: the ordinary case (single custom file, no core
        block aggregated at all) must be a complete no-op, mentioned group
        included -- this is not the mechanism that classifies it, it is
        simply never in scope (no core block to compare against)."""
        result = _strip_core_only_group_mentions(
            _REAL_01A_BULLET_ANSWER_WITH_CORE_NOISE,
            _REAL_CREDIT_NOTE_SECURITY_LOCK_RAW_TEXT,
        )
        assert result == _REAL_01A_BULLET_ANSWER_WITH_CORE_NOISE

    def test_does_not_affect_bloc9_08a_scenario(self):
        """Non-regression: same scenario as
        TestGroundedCoreOnlyGroups::test_bloc9_08a_scenario_not_flagged --
        must be a full no-op on the answer text, not just an empty
        core_only list."""
        answer = (
            "Pour un montant de 60 000€, il faut que l'utilisateur soit "
            "membre du groupe account.group_account_manager. Le groupe "
            "base.group_system est également mentionné dans le code pour "
            "le palier à 100 000€."
        )
        result = _strip_core_only_group_mentions(answer, _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT)
        assert result == answer


class TestCorrectSecurityLockThresholdContradictions:
    """ gap fix (2026-08-14, module 8/8, ):
    tests for _correct_security_lock_threshold_contradictions."""

    _BAD_VERBATIM_ANSWER = (
        "Responsable comptabilité : a le permission de valider jusqu'à 50 000€. "
        "Puisque le montant est de 60 000€, elle n'a pas le permission de valider ce document.\n\n"
        "Administrateur système : a le permission de valider les documents supérieurs à 100 000€. "
        "Puisque le montant est de 60 000€, elle a le permission de valider ce document."
    )

    _GOOD_ANSWER = (
        "Pour valider un document de 60 000€, il faut être membre du groupe "
        "account.group_account_manager (Responsable comptabilité), car le montant "
        "dépasse le seuil de 50 000€. Le verrou de 100 000€ réservé à "
        "base.group_system ne s'applique pas."
    )

    _QUESTION_60K = (
        "Qui a le permission de valider un document à 60 000€ dans le modèle "
        "custom.deep.document (module de sécurité à héritage profond) ?"
    )

    def test_corrects_live_bloc9_08a_verbatim_inversion(self):
        result = _correct_security_lock_threshold_contradictions(
            self._BAD_VERBATIM_ANSWER,
            _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT,
            self._QUESTION_60K,
        )
        assert "account.group_account_manager" in result
        assert "a donc le permission de valider ce document" in result
        assert "base.group_system" in result
        assert "ne s'applique pas à 60 000€" in result
        assert "n'a pas le permission de valider" not in result

    def test_no_op_when_answer_already_correct(self):
        result = _correct_security_lock_threshold_contradictions(
            self._GOOD_ANSWER,
            _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT,
            self._QUESTION_60K,
        )
        assert result == self._GOOD_ANSWER

    def test_no_op_when_no_amount_in_question(self):
        q_no_amount = "Quelles sont les règles de validation de custom.deep.document ?"
        result = _correct_security_lock_threshold_contradictions(
            self._BAD_VERBATIM_ANSWER,
            _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT,
            q_no_amount,
        )
        assert result == self._BAD_VERBATIM_ANSWER

    def test_no_op_when_no_lock_rules_in_raw_output(self):
        result = _correct_security_lock_threshold_contradictions(
            self._BAD_VERBATIM_ANSWER,
            "rien à voir ici",
            self._QUESTION_60K,
        )
        assert result == self._BAD_VERBATIM_ANSWER

    def test_corrects_bullet_list_inversion(self):
        bullet_bad = (
            "- Responsable comptabilité : a le permission de valider jusqu'à 50 000€. "
            "Puisque le montant est de 60 000€, elle n'a pas le permission de valider ce document.\n"
            "- Administrateur système : a le permission de valider les documents supérieurs à 100 000€. "
            "Puisque le montant est de 60 000€, elle a le permission de valider ce document."
        )
        result = _correct_security_lock_threshold_contradictions(
            bullet_bad,
            _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT,
            self._QUESTION_60K,
        )
        assert "account.group_account_manager" in result
        assert "a donc le permission de valider ce document" in result
        assert "ne s'applique pas à 60 000€" in result


class TestBackfillMissingSecurityLockAmountAmountAware:
    """ gap fix (2026-08-14, module 8/8 follow-up):
    amount-aware tests for _backfill_missing_security_lock_amount."""

    def test_does_not_backfill_100k_when_question_amount_is_60k(self):
        answer = "Le responsable comptabilité doit valider au-delà de 50 000€."
        q = "Qui valide un document de 60 000€ dans custom.deep.document ?"
        result = _backfill_missing_security_lock_amount(
            answer, _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT, question=q
        )
        # 50000 is present in answer, 100000 is > 60000 (not triggered) -> no backfill
        assert result == answer

    def test_does_not_backfill_when_can_view_amount_fact_present(self):
        answer = (
            "L'utilisateur NE PEUT PAS voir ce document de 30 000€.\n\n"
            "[FAIT DÉTERMINISTIQUE] can_view_amount() = False : l'utilisateur NE PEUT PAS voir cet enregistrement pour ce montant."
        )
        q = "Un utilisateur peut-il voir un document de 30 000€ ?"
        result = _backfill_missing_security_lock_amount(
            answer, _REAL_DEEP_INHERITANCE_SECURITY_RAW_TEXT, question=q
        )
        assert result == answer


class TestVerifyUsedSourcesDedup:
    """Section 391/392 (todo/contexte.txt): _verify_used_sources() must
    deduplicate by (source, title) so that two chunks retrieved from the
    same source document (e.g. two sections of the same wiki page), each
    cited via a distinct alias, produce a single SourceReference rather
    than a visible duplicate entry in the 'Sources :' block."""

    def test_two_aliases_same_document_collapse_to_one_source(self):
        alias_map = {
            "S1": {"document": "Premiere section du wiki vente...", "metadata": {
                "source": "wiki_vente.md", "type": "wiki",
                "title": "WIKI INTERNE MIRO KE — Processus de vente et CRM",
            }},
            "S2": {"document": "Deuxieme section, meme document...", "metadata": {
                "source": "wiki_vente.md", "type": "wiki",
                "title": "WIKI INTERNE MIRO KE — Processus de vente et CRM",
            }},
        }
        result = _verify_used_sources(["S1", "S2"], alias_map)
        assert len(result) == 1
        assert result[0].source == "wiki_vente.md"
        assert result[0].title == "WIKI INTERNE MIRO KE — Processus de vente et CRM"
        # First occurrence (retrieval order) wins -- S2's snippet is
        # dropped rather than merged into a synthetic combined snippet.
        assert result[0].snippet.startswith("Premiere section")

    def test_distinct_documents_are_not_collapsed(self):
        alias_map = {
            "S1": {"document": "Contenu A", "metadata": {
                "source": "doc_a.md", "type": "wiki", "title": "Doc A",
            }},
            "S2": {"document": "Contenu B", "metadata": {
                "source": "doc_b.md", "type": "wiki", "title": "Doc B",
            }},
        }
        result = _verify_used_sources(["S1", "S2"], alias_map)
        assert len(result) == 2
        assert {s.title for s in result} == {"Doc A", "Doc B"}

    def test_same_source_path_but_different_title_not_collapsed(self):
        """Belt-and-suspenders: dedup key is (source, title), not source
        alone -- a metadata inconsistency giving two different titles for
        the same file path should not silently merge them."""
        alias_map = {
            "S1": {"document": "Contenu A", "metadata": {
                "source": "multi_title.md", "type": "wiki", "title": "Titre A",
            }},
            "S2": {"document": "Contenu B", "metadata": {
                "source": "multi_title.md", "type": "wiki", "title": "Titre B",
            }},
        }
        result = _verify_used_sources(["S1", "S2"], alias_map)
        assert len(result) == 2


