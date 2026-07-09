"""
rag/schemas.py

Pydantic models for structured RAG output.
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SourceReference(BaseModel):
    """Reference to a source document used for answering."""
    model_config = ConfigDict(strict=True)

    source: str = Field(..., description="The name or path of the source file")
    doc_type: str = Field(..., description="Type of the document (e.g., pdf, wiki, code, ticket)")
    title: str = Field(..., description="Title or descriptive name of the source")
    snippet: str = Field(..., description="A short excerpt from the document showing the context")
    page: Optional[int] = Field(default=None, description="Page number if applicable (e.g., for PDFs)")


class LLMResponse(BaseModel):
    """Internal model for the LLM output before formatting."""
    model_config = ConfigDict(strict=True)
    
    answer: str = Field(..., description="The main text of the assistant's answer in French")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the answer from 0.0 to 1.0")


class AssistantResponse(BaseModel):
    """Structured response from the MIRO Assistant."""
    model_config = ConfigDict(strict=True)

    answer: str = Field(..., description="The main text of the assistant's answer in French")
    sources: List[SourceReference] = Field(default_factory=list, description="List of sources cited in the answer")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the answer from 0.0 to 1.0")
    ocr_warning: bool = Field(default=False, description="True if any of the sources come from a low-quality OCR scan")
