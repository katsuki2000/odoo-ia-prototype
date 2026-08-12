import pytest
from unittest.mock import patch, MagicMock

from rag.schemas import AssistantResponse, LLMResponse
from rag.graph import (
    query_graph, generate, format_output, _rank_and_cap_override_methods,
    _format_can_view_amount_fact, _question_suggests_automation_bypass,
    _extract_override_modules, _backfill_missing_override_modules,
    _extract_override_chain_amounts, _backfill_missing_override_chain_amount,
    _answer_denies_other_overrides, _answer_asserts_override_shortcircuit,
    _neutralize_override_count_denial, _neutralize_override_shortcircuit_sentence,
    _correct_override_cascade_contradictions,
)

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


# 2. Test OCR warning injection

def test_format_output_ocr_warning():
    state = {
        "response": AssistantResponse(answer="Voici la réponse.", confidence=0.8, sources=[]),
        "retrieved_chunks": [
            {"document": "test doc", "metadata": {"source": "scan.pdf", "ocr_quality": "low", "type": "pdf"}}
        ],
        "route": "documentaire",
    }
    result = format_output(state)
    assert result["response"].ocr_warning is True
    assert "qualité de lecture est limitée" in result["response"].answer
    assert len(result["response"].sources) == 1
    assert result["response"].sources[0].source == "scan.pdf"

# 3. Test format output WITHOUT OCR warning
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

# 4. Test full query graph with mocked LLM and retriever
@patch('rag.graph.ChatGroq')
@patch('rag.graph.get_retriever')
@patch('rag.graph.search_retrieve')
def test_query_graph_mocked(mock_search_retrieve, mock_get_retriever, mock_chat_groq):
    # Mock Retriever
    mock_get_retriever.return_value = (MagicMock(), MagicMock())
    mock_search_retrieve.return_value = [
        {"document": "Facture = Nouveau", "metadata": {"source": "facture.md"}}
    ]
    
    # Mock LLM
    mock_llm_instance = MagicMock()
    mock_chat_groq.return_value = mock_llm_instance
    mock_structured_llm = MagicMock()
    mock_llm_instance.with_structured_output.return_value = mock_structured_llm
    
    mock_structured_llm.invoke.return_value = LLMResponse(
        answer="Pour créer une facture, cliquez sur Nouveau.",
        confidence=0.95
    )
    
    response = query_graph("Comment créer une facture ?")
    
    assert isinstance(response, AssistantResponse)
    assert response.confidence == 0.95
    assert response.ocr_warning is False
    assert len(response.sources) == 1
    assert response.sources[0].source == "facture.md"


# Bloc 9 gap (2026-08-10, bloc9-01a-business): override-cascade forced
# dispatch must stay scoped to what the question actually asks about on a
# shared model, instead of dispatching every flagged method regardless of
# relevance and drowning the one finding that matters in synthesis context.
class TestRankAndCapOverrideMethods:
    def test_no_op_single_candidate(self):
        """Bloc 9 gap rerun (2026-08-11): cap lowered from 2 to 1 (see
        module-level comment above _MAX_OVERRIDE_CASCADE_DISPATCH in
        rag/graph.py) -- with only one flagged candidate to begin with,
        there is nothing to rank or drop."""
        methods = ["action_valider_avoir"]
        assert _rank_and_cap_override_methods("peu importe", methods) == methods

    def test_ranks_and_keeps_only_top_relevant_method(self):
        question = "Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?"
        methods = [
            "_compute_commercial_partner_id",
            "write",
            "action_valider_avoir",
            "_reverse_moves",
        ]
        result = _rank_and_cap_override_methods(question, methods)
        assert result == ["action_valider_avoir"]

    def test_two_candidates_still_gets_capped_to_one(self):
        """Bloc 9 gap, module 1/8 rerun (2026-08-10/11): the exact case that
        motivated lowering the cap from 2 to 1 -- exactly 2 flagged
        candidates on a shared model, one relevant and one not. The old
        cap=2 'no-op when <= cap' guard let both through untouched here,
        wasting a full hop of CI_MAX_HOPS on the irrelevant one."""
        question = "Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?"
        methods = ["_compute_commercial_partner_id", "action_valider_avoir"]
        result = _rank_and_cap_override_methods(question, methods)
        assert result == ["action_valider_avoir"]


# Bloc 9 gap (2026-08-10, bloc9-02b-no-groups): the deterministic
# can_view_amount fact injected into tool_observations must stay purely
# declarative -- a live run showed the synthesis LLM echoing an imperative
# second-person sentence ('ne doit JAMAIS etre recalcule ... reprendre ce
# verdict tel quel') verbatim as its entire final answer, with no actual
# explanation, once that instruction was embedded directly in the fact text.
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


# Bloc 9 gap (2026-08-10, bloc9-03c-urgente-trap, generalization check 3/8
# on custom_hr_leave_workflow): bare 'automatiq\w*' matched the everyday
# adverb "automatiquement" ("sa demande est-elle automatiquement validee ?"),
# an ordinary question about whether something happens without further
# action -- nothing to do with ir.actions.server/base.automation/sudo()
# bypass logic. On a model with real ServerAction nodes this forced an
# irrelevant analyser_actions_serveur dispatch, consuming a hop of the
# tight CI_MAX_HOPS=4 budget and crowding out a needed fact (has_group()
# required group) from the synthesis answer -- same failure shape as
# module 1/8's Gap 2, different trigger.
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


# Bloc 9 gap, found 2026-08-11 (module 1/8 rerun, bloc9-01a-business /
# bloc9-01b-technical, after the has_group()/cap/truncation fixes were all
# confirmed active): two further dropped-fact gaps on the same
# 'account.move.action_valider_avoir' override cascade -- see the
# module-level comment above _OVERRIDE_MODULE_RE/_OVERRIDE_CHAIN_AMOUNT_RE
# in rag/graph.py for the full live-run diagnosis. Fixture text below
# mirrors the real analyser_chaine_surcharge_methode output verbatim
# (3-module chain, same wording as the confirmed live raw check).
_REAL_OVERRIDE_CHAIN_RAW_TEXT = (
    "Chaîne de surcharge de 'account.move.action_valider_avoir' (3 modules, "
    "ordre d'exécution réel, pas l'ordre de dépendance):\n"
    "  1. module 'custom_credit_note_approval_vip' -- [account_move.py:L7-L14]\n"
    "     ⚠️ SUPER() NON GARDÉ: ...\n"
    "  2. module 'custom_credit_note_approval_regional' -- [account_move.py:L9-L15]\n"
    "     ⚠️ CHAINE RELATIONNELLE NON VÉRIFIÉE (Règle 3): 'action_valider_avoir' "
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
        """Bloc9-01b-technical live failure: base module correctly enumerated
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
        """Bloc9-01a-business live failure: the regional module's 20000e
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
        """Bloc 9 gap, found 2026-08-11 (module 5/8, bloc9-05c-no-link-trap
        live run, same day as module 5/8's exception_conditions fix in
        semgrep_locks_analyzer.py): _OVERRIDE_CHAIN_AMOUNT_RE ('rec.<attr> >
        <digits>') is not actually specific to
        analyser_chaine_surcharge_methode's output shape -- the same literal
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
        analyser_verrous_securite blocks, no analyser_chaine_surcharge_
        methode block at all -- no 'module ''x''' line anywhere)."""
        contaminated_raw_text = (
            "Analyse des verrous Python ([asset_loan.py:L1-L30]...):\n"
            "  - Messages de verrous (UserError/ValidationError):\n"
            "    * \"Separation des roles requise...\" (condition : "
            "rec.demande_achat_liee_id and rec.demande_achat_liee_id.montant_estime > 2000 "
            "and rec.demande_achat_liee_id.demandeur_id == rec.beneficiaire_id)\n\n"
            "Analyse des verrous Python ([purchase_request.py:L1-L28]...):\n"
            "  - Messages de verrous (UserError/ValidationError):\n"
            "    * \"Vous n'avez pas le droit de valider cette demande d'achat.\" "
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


# Bloc 9 gap, module 1/8 (2026-08-12, bloc9-01b-technical): the marker-only
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
        """Reproduces the reported bloc9-01b-technical live failure end to
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


