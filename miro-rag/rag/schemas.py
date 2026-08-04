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
