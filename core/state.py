"""Workflow state shared by every node of the LangGraph agent network."""

from typing import List, Optional, TypedDict

from langchain_core.messages import BaseMessage

from core.schemas import AssistantResponse


class RAGState(TypedDict):
    """Workflow state container for the LangGraph agent network."""
    question: str
    chat_history: List[BaseMessage]
    uid: Optional[int]
    skills: Optional[dict]
    timing: dict
    retrieved_chunks: List[dict]
    raw_answer: str
    route: Optional[str]
    response: Optional[AssistantResponse]
    user_groups: List[int | str]
    user_groups_complete: Optional[bool]
    resolved_concept: Optional[dict]
    last_route: Optional[str]
    evidence_status: Optional[str]
    loop_resolved_concept: Optional[dict]
    investigation_plan: Optional[dict]
    sources_fallback_eligible: Optional[bool]
    ci_evidence_sufficiency: Optional[dict]
    raw_tool_output: Optional[str]
    source_mode: Optional[str]
    language: Optional[str]
