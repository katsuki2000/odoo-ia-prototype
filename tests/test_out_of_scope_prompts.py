"""Both branch prompts carry the out-of-scope refusal and let the model translate it."""

from core.guardrails import OUT_OF_SCOPE_ANSWER
from document_rag.prompts import DOCUMENTARY_RAG_SYSTEM_PROMPT
from erp_data.prompts import ORM_AGENT_SYSTEM_PROMPT

TRANSLATION_RULE = "traduite dans la langue de la question"


def test_both_branch_prompts_ask_for_the_out_of_scope_refusal():
    assert OUT_OF_SCOPE_ANSWER in ORM_AGENT_SYSTEM_PROMPT
    assert "{out_of_scope_answer}" in DOCUMENTARY_RAG_SYSTEM_PROMPT


def test_fixed_refusals_are_translated_into_the_question_language():
    assert TRANSLATION_RULE in ORM_AGENT_SYSTEM_PROMPT
    assert DOCUMENTARY_RAG_SYSTEM_PROMPT.count(TRANSLATION_RULE) == 2
