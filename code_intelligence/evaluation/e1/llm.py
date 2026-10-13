"""LLM callable for the E1 harness, built from the project's environment (no secret, no path here)."""

from __future__ import annotations

from .arbitration import LlmCallable


def resolve_e1_llm_callable() -> LlmCallable:
    """(system_prompt, user_prompt) -> text, over the chat model configured by the project's .env."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from core.llm.llm_client import get_chat_llm

    chat = get_chat_llm(temperature=0.0, max_retries=0)

    def call(system_prompt: str, user_prompt: str) -> str:
        response = chat.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        return str(response.content or "")

    return call
