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
    DOCUMENTAIRE = "documentaire"
    DONNEES_ERP = "donnees_erp"
    HYBRIDE = "hybride"
    CODE_INTELLIGENCE = "code_intelligence"

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
    User-facing title for a chunk's metadata -- section 338 (todo/contexte.txt):
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
            "single call, never a stable id or file path -- section 336 "
            "(todo/contexte.txt), lets format_output() show only chunks "
            "genuinely used instead of every chunk retrieved."
        ),
    )


class OmittedForAuthorization(BaseModel):
    """
    A single element withheld from the answer because the requester's permissions do not cover it.
    """
    model_config = ConfigDict(strict=True)

    label: str = Field(..., description="What was omitted (rule names, or tool+model), never the withheld content itself")
    reason: str = Field(..., description="Explicit, human-readable authorization reason for the omission")


class AssistantResponse(BaseModel):
    """Structured response from the MIRO Assistant."""
    model_config = ConfigDict(strict=True)

    answer: str = Field(..., description="The main text of the assistant's answer in French")
    sources: List[SourceReference] = Field(default_factory=list, description="List of sources cited in the answer")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the answer from 0.0 to 1.0")
    ocr_warning: bool = Field(default=False, description="True if any of the sources come from a low-quality OCR scan")
    omitted_for_authorization: List[OmittedForAuthorization] = Field(
        default_factory=list,
        description="Elements withheld because the requester's permissions do not cover them",
    )
    route: Optional[str] = Field(
        default=None,
        description="Which QueryRoute branch handled this turn",
    )
    resolved_concept: Optional[dict] = Field(
        default=None,
        description="Deterministic business_resolver output for this turn",
    )
    evidence_status: Optional[str] = Field(
        default=None,
        description="Sourcing evidence status (RESOLU/NON_RESOLU)",
    )
    loop_resolved_concept: Optional[dict] = Field(
        default=None,
        description="Concept the code_intelligence_agent loop actually used (LLM arbitration, model cap)",
    )
    investigation_plan: Optional[dict] = Field(
        default=None,
        description="Structured investigation plan produced before tool execution (Bloc P1)",
    )
    ci_evidence_sufficiency: Optional[dict] = Field(
        default=None,
        description=(
            "Post-analysis CI answer sufficiency verdict (sufficient/insufficient/"
            "conflicting, core/evidence/evidence_sufficiency.py) -- only set when the "
            "code_intelligence_agent branch ran this turn. Set regardless of "
            "whether the RAG fallback fired, so the original CI verdict stays "
            "traceable even when the final answer came from generate() instead."
        ),
    )
    rag_fallback: bool = Field(
        default=False,
        description=(
            "True when the final answer was produced by the documentary RAG "
            "fallback after the code_intelligence_agent branch ran, so the "
            "CI sufficiency verdict does not describe the answer returned."
        ),
    )
    verification: Optional[VerificationReport] = Field(
        default=None,
        description=(
            "Deterministic claim verification of the final answer (todo/contexte.txt "
            "section 1121): counts of number, group and method claims and the ones "
            "no evidence supports. None when the verifier did not run this turn."
        ),
    )
    evidence_dossier: List[Evidence] = Field(
        default_factory=list,
        description=(
            "Structured, tool-provenance Evidence gathered this turn (Bloc B2, "
            "todo/contexte.txt section 622) via core/evidence_collector.py. "
            "Distinct from 'sources' (SourceReference, UI-facing citation "
            "derived from RAG chunks) -- this is the raw fact + provenance a "
            "CI/ORM tool actually produced while it worked. Populated "
            "incrementally as each tool wrapper is wired (rollout in progress, "
            "not yet all 24+2 tools) -- an empty list does not mean no "
            "Evidence was gathered, only that no wired tool ran this turn."
        ),
    )
