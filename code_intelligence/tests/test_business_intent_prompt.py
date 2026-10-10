from code_intelligence.agent.investigation_llm import (
    _INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    build_intent_classification_messages,
)


def test_intent_prompt_prioritizes_business_user_questions():
    prompt = _INTENT_CLASSIFICATION_SYSTEM_PROMPT.lower()

    assert "utilisateurs métiers" in prompt
    assert "qui approuve ou a accès" in prompt
    assert "comment effectuer une action dans odoo" in prompt
    assert "pourquoi une opération est bloquée" in prompt
    assert "état courant" in prompt
    assert "analyse du code" in prompt


def test_intent_prompt_keeps_closed_category_contract():
    prompt = _INTENT_CLASSIFICATION_SYSTEM_PROMPT

    assert "EXACTEMENT une des catégories" in prompt
    assert "general_code_inquiry" in prompt
    assert "Reponds uniquement avec la catégorie choisie" in prompt


def test_business_prompt_is_used_for_classifier_messages():
    question = "Pourquoi ma facture est-elle bloquée ?"
    messages = build_intent_classification_messages(question)

    assert len(messages) == 2
    assert _INTENT_CLASSIFICATION_SYSTEM_PROMPT in messages[0].content
    assert question in messages[1].content
