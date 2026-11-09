"""Both branch prompts carry the out-of-scope refusal."""

from core.guardrails import OUT_OF_SCOPE_ANSWER
from document_rag.prompts import DOCUMENTARY_RAG_SYSTEM_PROMPT
from erp_data.prompts import ORM_AGENT_SYSTEM_PROMPT


def test_both_branch_prompts_ask_for_the_out_of_scope_refusal():
    assert OUT_OF_SCOPE_ANSWER in ORM_AGENT_SYSTEM_PROMPT
    assert "{out_of_scope_answer}" in DOCUMENTARY_RAG_SYSTEM_PROMPT
