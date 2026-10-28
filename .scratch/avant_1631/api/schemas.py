"""Pydantic request and response schemas for the MIRO API."""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class AskRequestV1(BaseModel):
    """Request body for /api/v1/ask."""
    question: str = Field(..., min_length=1)
    session_id: str
    user_uid: int
    company_id: int
    language: Optional[str] = Field(
        default=None,
        description="Request language tag (BCP 47, e.g. fr or fr-CA); falls back to Accept-Language.",
    )
    skills: dict[str, bool] = Field(default_factory=dict)
    source_mode: Optional[Literal["documentation", "systeme"]] = Field(
        default=None,
        description=(
            "Source chosen by the user in the UI: 'documentation' forces the RAG "
            "documentary path, 'systeme' excludes the documentary route; absent = automatic routing"
        ),
    )


class AskResponseV1(BaseModel):
    """Response body for /api/v1/ask."""
    answer: str
    question: str
    session_id: str
    sources: list[dict] = Field(default_factory=list)
    confidence: float = 1.0
    ocr_warning: bool = False
    route: Optional[str] = None
    evidence_status: Optional[str] = None
    resolved_concept: Optional[dict] = None
    omitted_for_authorization: list[dict] = Field(default_factory=list)
    investigation_plan: Optional[dict] = None
    evidence_dossier: list[dict] = Field(
        default_factory=list,
        description=(
            "Structured tool-provenance Evidence"
            "fact+provenance an ORM/CI tool produced this turn."
        ),
    )


class AskJobRequestV1(AskRequestV1):
    """Request body for POST /api/v1/ask/jobs; the caller chooses the job id."""
    job_id: str = Field(..., pattern=r"^[0-9a-f]{32}$")


class AskJobAcceptedV1(BaseModel):
    job_id: str


class AskJobStatusV1(BaseModel):
    """State of an asynchronous ask job; result or error is set once it is no longer pending."""
    status: Literal["pending", "done", "error"]
    question: str
    elapsed_ms: int
    result: Optional[AskResponseV1] = None
    error_status: Optional[int] = None
    error_detail: Optional[str] = None


class StatsResponse(BaseModel):
    """Response body for the /stats endpoint."""
    collection_name: str
    document_count: int


class ReindexResponse(BaseModel):
    """Response body for the /reindex endpoint."""
    status: str
    document_count: int


class ReindexRequestV1(BaseModel):
    """Request body for /api/v1/reindex."""
    scope: Literal["full", "incremental"] = Field(
        "incremental",
        description="Use 'full' to clear/rebuild or 'incremental' to process changes only",
    )
    path: Optional[str] = Field(
        None,
        description="Optional file or directory path to process",
    )


class ReindexResponseV1(BaseModel):
    """Response body for /api/v1/reindex."""
    status: str
    scope: str
    result: dict[str, Any]
    total_chunks: int


class IngestionStatusResponse(BaseModel):
    """Response body for /api/v1/ingestion/status."""
    last_ingestion_time: Optional[str]
    total_chunks: int
    files_monitored: int
    watcher_status: dict[str, Any]
    scheduler_status: Optional[dict[str, Any]] = None
    last_scan_type: Optional[str] = None


class ScheduledScanResponse(BaseModel):
    """Response body for triggering or checking scheduled scan."""
    status: str
    scan_type: str
    result: dict[str, Any]
    last_ingestion_time: Optional[str]


class ModuleCoverageResponse(BaseModel):
    """Response body for /api/v1/modules endpoint."""
    supported: list[str]
    code_indexed: list[str]
    not_covered: list[str]
