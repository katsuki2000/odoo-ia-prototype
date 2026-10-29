"""Workflow state shared by the LangGraph agent network."""

from typing import List, Optional, TypedDict
from langchain_core.messages import BaseMessage
from core.schemas import AssistantResponse


class RAGState(TypedDict):
    question: str
    chat_history: List[BaseMessage]
    uid: Optional[int]
    timing: dict
    retrieved_chunks: List[dict]
    route: Optional[str]
    response: Optional[AssistantResponse]
    last_route: Optional[str]
    sources_fallback_eligible: Optional[bool]
    raw_tool_output: Optional[str]
    source_mode: Optional[str]
    language: Optional[str]
