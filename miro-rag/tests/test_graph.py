import pytest
from unittest.mock import patch, MagicMock

from rag.schemas import AssistantResponse, LLMResponse
from rag.graph import (
    query_graph, generate, format_output, _rank_and_cap_override_methods,
    _format_can_view_amount_fact, _question_suggests_automation_bypass,
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
    def test_no_op_below_cap(self):
        methods = ["action_valider_avoir", "_compute_commercial_partner_id"]
        assert _rank_and_cap_override_methods("peu importe", methods) == methods

    def test_ranks_relevant_method_first_when_over_cap(self):
        question = "Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?"
        methods = [
            "_compute_commercial_partner_id",
            "write",
            "action_valider_avoir",
            "_reverse_moves",
        ]
        result = _rank_and_cap_override_methods(question, methods)
        assert len(result) == 2
        assert "action_valider_avoir" in result


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

