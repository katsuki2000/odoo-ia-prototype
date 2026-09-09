"""
core/prompts.py

Backward-compatible facade re-exporting documentary RAG prompt utilities.
"""

from document_rag.prompts import (
    DOCUMENTARY_RAG_SYSTEM_PROMPT as SYSTEM_PROMPT,
    DOCUMENTARY_RAG_SYSTEM_PROMPT,
    build_rag_messages as build_messages,
    build_rag_messages,
)

__all__ = [
    "SYSTEM_PROMPT",
    "DOCUMENTARY_RAG_SYSTEM_PROMPT",
    "build_messages",
    "build_rag_messages",
]
