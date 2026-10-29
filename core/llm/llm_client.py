"""LLM client factory and the single call site for chat completions."""

import logging
from typing import Optional

from config.settings import (
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_API_KEY,
    LLM_MAX_RETRIES,
    LLM_NO_THINK_MARKER,
    LLM_REQUEST_TIMEOUT_SECONDS,
    require_inference_server,
)

logger = logging.getLogger(__name__)


def with_no_think(prompt: str) -> str:
    return f"{prompt} {LLM_NO_THINK_MARKER}" if LLM_NO_THINK_MARKER else prompt


def get_chat_llm(
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    max_retries: int = LLM_MAX_RETRIES,
    model_kwargs: Optional[dict] = None,
):
    """Build the chat client for the configured Ollama server (OpenAI-compatible API)."""
    from langchain_openai import ChatOpenAI
    kw = dict(model_kwargs or {})
    penalties = {name: kw.pop(name) for name in ("frequency_penalty", "presence_penalty") if kw.get(name) is not None}
    return ChatOpenAI(
        model=model or LLM_MODEL,
        base_url=require_inference_server(base_url or LLM_BASE_URL),
        api_key=api_key or LLM_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        model_kwargs=kw,
        **penalties,
    )


def invoke_llm(llm, messages: list):
    """Call the model once; connection retries are the client's own."""
    return llm.invoke(messages)
