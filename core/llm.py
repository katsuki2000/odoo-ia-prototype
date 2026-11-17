"""LLM client factory and the single call site for chat completions."""

from config.settings import (
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_API_KEY,
    LLM_MAX_RETRIES,
    LLM_TEMPERATURE,
    LLM_REQUEST_TIMEOUT_SECONDS,
    require_inference_server,
)


def get_chat_llm(
    *,
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
):
    """Build the chat client for the configured Ollama server (OpenAI-compatible API)."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL,
        base_url=require_inference_server(LLM_BASE_URL),
        api_key=LLM_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=LLM_MAX_RETRIES,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        reasoning_effort=reasoning_effort,
    )


def invoke_llm(llm, messages: list):
    """Call the model once; connection retries are the client's own."""
    return llm.invoke(messages)
