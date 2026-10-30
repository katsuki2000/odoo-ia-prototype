"""Workflow state shared by the LangGraph agent network."""

from typing import TypedDict

from langchain_core.messages import BaseMessage

from core.schemas import AssistantResponse


class RAGState(TypedDict, total=False):
    question: str
    chat_history: list[BaseMessage]
    uid: int | None
    timing: dict
    retrieved_chunks: list[dict]
    route: str | None
    response: AssistantResponse | None
    structured_failed: bool | None
    raw_tool_output: str | None
    source_mode: str | None
    language: str | None
