"""Pydantic models for structured output."""

import logging
import os
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.evidence.evidence import Evidence

logger = logging.getLogger(__name__)


class QueryRoute(str, Enum):
    """Branch that answers a question."""
    DOCUMENTARY = "documentation"
    ERP_DATA = "system"


class ClaimType(str, Enum):
    NUMBER = "number"
    GROUP = "group"
    METHOD = "method"


class VerifierMode(str, Enum):
    OFF = "off"
    REPORT = "report"
    ENFORCE = "enforce"

    @classmethod
    def parse(cls, value: object) -> "VerifierMode":
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            logger.warning("Unknown ANSWER_VERIFIER_MODE %r -- falling back to '%s'.", value, cls.REPORT.value)
            return cls.REPORT


class UnsupportedClaim(BaseModel):
    claim_type: ClaimType
    text: str
    reason: str


class VerificationReport(BaseModel):
    """Claim counts are taken before any action, so the unsupported rate stays measurable in enforce mode."""

    mode: VerifierMode
    claims_total: int = Field(default=0, ge=0)
    unsupported_claims: int = Field(default=0, ge=0)
    claims_by_type: dict[ClaimType, int] = Field(default_factory=dict)
    unsupported_by_type: dict[ClaimType, int] = Field(default_factory=dict)
    unsupported: list[UnsupportedClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unsupported_within_total(self) -> "VerificationReport":
        if self.unsupported_claims > self.claims_total:
            raise ValueError("unsupported_claims cannot exceed claims_total")
        return self


class SourceReference(BaseModel):
    """Reference to a source document used for answering."""
    model_config = ConfigDict(strict=True)

    source: str = Field(..., description="The name or path of the source file")
    doc_type: str = Field(..., description="Type of the document (e.g., pdf, wiki, code, ticket)")
    title: str = Field(..., description="Title or descriptive name of the source")
    snippet: str = Field(..., description="A short excerpt from the document showing the context")
    page: int | None = Field(default=None, description="Page number if applicable (e.g., for PDFs)")


def source_display_title(meta: dict) -> str:
    """Title of a chunk for display: its title, else the file name, never the full path."""
    return meta.get("title") or os.path.basename(meta.get("source", "unknown"))


class LLMResponse(BaseModel):
    """Internal model for the LLM output before formatting."""
    model_config = ConfigDict(strict=True)

    answer: str = Field(..., description="The main text of the assistant's answer in French")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the answer from 0.0 to 1.0")
    used_sources: list[str] = Field(
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
    sources: list[SourceReference] = Field(default_factory=list, description="List of sources cited in the answer")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the answer from 0.0 to 1.0")
    ocr_warning: bool = Field(default=False, description="True if any of the sources come from a low-quality OCR scan")
    route: str | None = Field(
        default=None,
        description="Which QueryRoute branch handled this turn",
    )
    verification: VerificationReport | None = Field(
        default=None,
        description="Deterministic claim verification of the final answer; None when the verifier did not run.",
    )
    evidence_dossier: list[Evidence] = Field(
        default_factory=list,
        description="Facts produced by the ORM tools this turn, with their provenance; distinct from the UI-facing 'sources'.",
    )
