"""
rag/schemas.py

Pydantic models for structured RAG output.
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ── Routing ───────────────────────────────────────────────────────────────────

class QueryRoute(str, Enum):
    """Classification of the query type for routing."""
    DOCUMENTAIRE = "documentaire"
    DONNEES_ERP = "donnees_erp"
    HYBRIDE = "hybride"
    CODE_INTELLIGENCE = "code_intelligence"


class DataQueryIntent(BaseModel):
    """Structured intent extracted by the LLM for ERP data queries."""
    model_config = ConfigDict(strict=True)

    data_source: str = Field(
        ...,
        description="The data source to query: 'sales' for sales data, 'tickets' for support tickets"
    )
    operation: str = Field(
        ...,
        description="The operation to perform: 'sum', 'count', 'filter', 'list', 'max', 'min'"
    )
    filters: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value filters to apply, e.g. {'client': 'Société Dupont', 'statut': 'facturé'}"
    )
    target_field: str = Field(
        default="",
        description="The field to aggregate on, e.g. 'montant' for sum/max/min operations"
    )


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


class OmittedForAuthorization(BaseModel):
    """
    Bloc 7 / J23-J24: a single element withheld from the answer because
    the demandeur's real rights don't cover it -- distinct from the
    confidence/coverage score and from sourcing verification, per the
    J23-24 requirement not to break the sourcing principle by conflating
    the two.
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
        description="Bloc 7 (J23-24): elements withheld because the demandeur's rights don't cover them",
    )
    route: Optional[str] = Field(
        default=None,
        description=(
            "H1c support (todo/plan.md, 2026-08-19): which QueryRoute branch "
            "actually handled this turn, set centrally in rag/graph.py's "
            "format_output() node. Lets the caller (api/main.py) persist it "
            "as next turn's last_route for route()'s sticky-routing fallback "
            "-- never consumed inside the graph itself."
        ),
    )
    resolved_concept: Optional[dict] = Field(
        default=None,
        description=(
            "H1b-ii support (todo/contexte.txt section 64/70, 2026-08-20): "
            "the deterministic business_resolver output for this turn (dict "
            "form of ResolvedConcept), set centrally in rag/graph.py's "
            "format_output() node from RAGState.resolved_concept -- itself "
            "either the current question's own resolution or the previous "
            "turn's, reused by route()'s _sticky_concept_or_resolve fallback "
            "when the current question carries no resolvable business term. "
            "Lets the caller (api/main.py) persist it as next turn's "
            "last_resolved_concept -- never consumed inside the graph via "
            "this field itself (nodes read RAGState directly)."
        ),
    )
    evidence_status: Optional[str] = Field(
        default=None,
        description=(
            "H3 support (todo/contexte.txt, 2026-08-20), Phase 1 -- "
            "observational only: RESOLU/NON_RESOLU/CONFLIT computed by "
            "rag/evidence_check.py's check_evidence(), set centrally in "
            "rag/graph.py's format_output() node from RAGState.evidence_status. "
            "None on every branch except code_intelligence (the only branch "
            "with a resolved_concept to reconcile). Does not currently affect "
            "tool dispatch, prompt content, or gating -- surfaced purely for "
            "measurement against the adversarial benchmark before any future "
            "step decides what each status should actually change."
        ),
    )
