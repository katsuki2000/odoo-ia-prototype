"""Both answer prompts carry the Markdown rules that the assistant panel renders."""

from core.markdown_format import MARKDOWN_FORMAT_RULES
from document_rag.generation.prompts import build_rag_messages
from erp_data.agent.prompts import ORM_AGENT_SYSTEM_PROMPT


def test_erp_prompt_carries_the_markdown_rules():
    assert MARKDOWN_FORMAT_RULES in ORM_AGENT_SYSTEM_PROMPT


def test_documentary_prompt_carries_the_markdown_rules():
    system_message = build_rag_messages("question", "context")[0]
    assert MARKDOWN_FORMAT_RULES in system_message.content
