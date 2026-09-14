"""Pydantic request and response schemas for the MIRO API."""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class AskRequestV1(BaseModel):
    """Request body for /api/v1/ask."""
    question: str = Field(..., min_length=1)
    session_id: str
    user_uid: int
    company_id: int
    skills: dict[str, bool] = Field(default_factory=dict)
    active_model: Optional[str] = Field(
        default=None,
        description="Technical model name of the Odoo record open in the systray at ask-time",
    )
    active_id: Optional[int] = Field(
        default=None,
        description="Record id of active_model, propagated alongside it",
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
            "Structured tool-provenance Evidence (Bloc B2, todo/contexte.txt "
            "section 622/636). Distinct from 'sources' -- this is the raw "
            "fact+provenance an ORM/CI tool produced this turn."
        ),
    )


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
