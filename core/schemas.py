"""
core/schemas.py

Pydantic models for structured output.
"""

import os
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from core.evidence.evidence import Evidence
from core.verification.claims import VerificationReport


# ── Routing ───────────────────────────────────────────────────────────────────

class QueryRoute(str, Enum):
    """Classification of the query type for routing."""
    DOCUMENTARY = "documentation"
    ERP_DATA = "system"


class SourceReference(BaseModel):
    """Reference to a source document used for answering."""
    model_config = ConfigDict(strict=True)

    source: str = Field(..., description="The name or path of the source file")
    doc_type: str = Field(..., description="Type of the document (e.g., pdf, wiki, code, ticket)")
    title: str = Field(..., description="Title or descriptive name of the source")
    snippet: str = Field(..., description="A short excerpt from the document showing the context")
    page: Optional[int] = Field(default=None, description="Page number if applicable (e.g., for PDFs)")


def source_display_title(meta: dict) -> str:
    """
    User-facing title for a chunk's metadata:
    ingestion stores the absolute file path as 'source' (separate, unfixed
    debt), so falling back to it directly leaks the local filesystem layout
    into the answer text. Falls back to the basename instead when 'title' is
    absent, never the full path.
    """
    title = meta.get("title")
    if title:
        return title
    return os.path.basename(meta.get("source", "unknown"))


class LLMResponse(BaseModel):
    """Internal model for the LLM output before formatting."""
    model_config = ConfigDict(strict=True)
    
    answer: str = Field(..., description="The main text of the assistant's answer in French")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the answer from 0.0 to 1.0")
    used_sources: List[str] = Field(
        default_factory=list,
        description=(
            "Short per-turn source aliases (e.g. 'S1', 'S2', matching the "
            "'[Source Sx]' markers in the supplied context) that were "
            "actually drawn on to write 'answer'. Aliases are local to this "
            "single call, never a stable id or file path. They let "
            "format_output() show only chunks "
            "genuinely used instead of every chunk retrieved."
        ),
    )


class AssistantResponse(BaseModel):
    """Structured response from the MIRO Assistant."""
    model_config = ConfigDict(strict=True)

    answer: str = Field(..., description="The main text of the assistant's answer in French")
    sources: List[SourceReference] = Field(default_factory=list, description="List of sources cited in the answer")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the answer from 0.0 to 1.0")
    ocr_warning: bool = Field(default=False, description="True if any of the sources come from a low-quality OCR scan")
    route: Optional[str] = Field(
        default=None,
        description="Which QueryRoute branch handled this turn",
    )
    verification: Optional[VerificationReport] = Field(
        default=None,
        description=(
            "Deterministic claim verification of the final answer: counts of number, group and method claims and the ones "
            "no evidence supports. None when the verifier did not run this turn."
        ),
    )
    evidence_dossier: List[Evidence] = Field(
        default_factory=list,
        description=(
            "Structured, tool-provenance Evidence gathered this turn "
            "via core/evidence/evidence_collector.py. "
            "Distinct from 'sources' (SourceReference, UI-facing citation "
            "derived from RAG chunks) -- this is the raw fact + provenance an "
            "ORM tool actually produced while it worked. An empty list means "
            "no ORM tool recorded Evidence this turn."
        ),
    )
