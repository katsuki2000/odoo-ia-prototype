"""Prompts carry the out-of-scope refusal, its translation rule and the absent-concept rule."""

from config.settings import OUT_OF_SCOPE_ANSWER
from document_rag.generation.prompts import DOCUMENTARY_RAG_SYSTEM_PROMPT
from erp_data.agent.prompts import NO_READ_REMINDER, ORM_AGENT_SYSTEM_PROMPT
from erp_data.runtime.langchain_tools import NO_MODEL_HINT

TRANSLATION_RULE = "traduite dans la langue de la question"


def test_both_branch_prompts_ask_for_the_out_of_scope_refusal():
    assert OUT_OF_SCOPE_ANSWER in ORM_AGENT_SYSTEM_PROMPT
    assert "{out_of_scope_answer}" in DOCUMENTARY_RAG_SYSTEM_PROMPT


def test_fixed_refusals_are_translated_into_the_question_language():
    assert TRANSLATION_RULE in ORM_AGENT_SYSTEM_PROMPT
    assert DOCUMENTARY_RAG_SYSTEM_PROMPT.count(TRANSLATION_RULE) == 2


def test_a_concept_without_model_is_reported_as_unavailable_in_the_three_texts():
    assert "ne le remplace pas" in ORM_AGENT_SYSTEM_PROMPT
    assert "n'est pas disponible" in NO_READ_REMINDER
    assert "not available to the requester" in NO_MODEL_HINT


def test_absence_is_concluded_only_after_fields_and_a_shorter_word_were_tried():
    assert "champ du modèle que la question nomme comme sujet" in ORM_AGENT_SYSTEM_PROMPT
    assert "jamais d'un modèle trouvé par un mot du concept" in ORM_AGENT_SYSTEM_PROMPT
    assert "sa racine" in ORM_AGENT_SYSTEM_PROMPT
    assert "ni champ" in NO_READ_REMINDER
    assert "field of the model the question names" in NO_MODEL_HINT
    assert "shorter root word" in NO_MODEL_HINT


def test_the_no_read_reminder_asks_for_an_answer_without_comment_on_its_instructions():
    assert "Ne commente pas ces consignes" in NO_READ_REMINDER
