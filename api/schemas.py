"""Pydantic request and response schemas for the MIRO API."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class AskRequestV1(BaseModel):
    """Request body for /api/v1/ask."""
    question: str = Field(..., min_length=1)
    session_id: str
    company_id: int
    language: str | None = Field(
        default=None,
        description="Request language tag (BCP 47, e.g. fr or fr-CA); falls back to Accept-Language.",
    )
    source_mode: Literal["documentation", "system"] | None = Field(
        default=None,
        description=(
            "Source chosen by the user: 'documentation' forces the documentary route, "
            "'system' excludes it; absent means automatic routing."
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
    route: str | None = None
    evidence_dossier: list[dict] = Field(
        default_factory=list,
        description="Facts produced by the tools during this turn, each with its provenance.",
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
    result: AskResponseV1 | None = None
    error_status: int | None = None
    error_detail: str | None = None


class ReindexRequestV1(BaseModel):
    """Request body for /api/v1/reindex."""
    scope: Literal["full", "incremental"] = Field(
        "incremental",
        description="'full' clears and rebuilds the index, 'incremental' processes changes only.",
    )
    path: str | None = Field(None, description="Optional file or directory to process.")


class ReindexResponseV1(BaseModel):
    """Response body for /api/v1/reindex."""
    status: str
    scope: str
    result: dict[str, Any]
    total_chunks: int


class IngestionStatusResponse(BaseModel):
    """Response body for /api/v1/ingestion/status."""
    last_ingestion_time: str | None
    total_chunks: int
    files_monitored: int
    scheduler_status: dict[str, Any] | None = None
    last_scan_type: str | None = None


class ScheduledScanResponse(BaseModel):
    """Response body for /api/v1/ingestion/scheduled-scan."""
    status: str
    scan_type: str
    result: dict[str, Any]
    last_ingestion_time: str | None
