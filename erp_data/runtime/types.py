from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.evidence.evidence import Evidence


class OrmObservation(BaseModel):
    model_config = ConfigDict(strict=True)

    tool: str
    model: str
    method: str
    request: dict[str, Any] = Field(default_factory=dict)
    row_count: int = 0
    truncated: bool = False
    execution_identity: int
    read_at: str
    company_id: Optional[int] = None
    company_ids: Optional[list[int]] = None


class OrmToolResult(BaseModel):
    model_config = ConfigDict(strict=True)

    observation: OrmObservation
    evidence: list[Evidence]
    text: str
