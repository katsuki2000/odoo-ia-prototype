"""The reasoning effort reaches the LLM request only when it is set."""

from langchain_core.messages import HumanMessage

import config.settings as settings
from core.llm.llm_client import get_chat_llm
from document_rag import generate_node


def request_payload(**kwargs):
    llm = get_chat_llm(base_url="http://127.0.0.1:11434/v1", model="m", api_key="k", **kwargs)
    return llm._get_request_payload([HumanMessage(content="question")])


def test_the_request_carries_the_effort_when_it_is_set():
    assert request_payload(reasoning_effort="none")["reasoning_effort"] == "none"


def test_the_request_is_unchanged_without_an_effort():
    assert "reasoning_effort" not in request_payload()


def test_the_documentary_answer_uses_the_rag_setting(monkeypatch):
    seen = {}
    monkeypatch.setattr(generate_node, "_build_llm", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(settings, "RAG_REASONING_EFFORT", "none")
    generate_node._build_answer_llm()
    assert seen["reasoning_effort"] == "none"
    assert seen["max_tokens"] == settings.DOCUMENT_MAX_TOKENS


def test_the_erp_agent_uses_the_erp_setting(monkeypatch):
    from erp_data import orm_agent_helpers

    seen = {}
    monkeypatch.setattr(orm_agent_helpers, "get_chat_llm", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(settings, "ERP_REASONING_EFFORT", "none")
    orm_agent_helpers._build_llm(temperature=0.0, max_tokens=512)
    assert seen == {"reasoning_effort": "none", "temperature": 0.0, "max_tokens": 512}
