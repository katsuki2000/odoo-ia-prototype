"""Evidence: the fact an ORM tool produced while it worked, with its provenance.

Distinct from SourceReference (core/schemas.py), which is the UI-facing citation of a RAG chunk.
"""

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSourceType(str, Enum):
    ORM = "orm"


def _canonical_json(value: Any) -> str:
    """Key-sorted compact JSON; non-JSON types (e.g. a datetime) go through str()."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_content_hash(
    source_type: EvidenceSourceType,
    claim: str,
    value: Any,
    source: str,
    scope: dict[str, Any],
) -> str:
    """Deterministic evidence_id: the same fact reported twice hashes to the same id (32 hex chars of SHA-256)."""
    payload = _canonical_json({
        "source_type": source_type.value,
        "claim": claim,
        "value": value,
        "source": source,
        "scope": scope,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class Evidence(BaseModel):
    model_config = ConfigDict(strict=True)

    evidence_id: str = Field(..., description="stable_content_hash() of this evidence's canonical payload")
    source_type: EvidenceSourceType
    claim: str = Field(..., description="What this evidence asserts, in plain language")
    value: Any = Field(default=None, description="The concrete fact/value backing the claim")
    source: str = Field(
        ...,
        description="Which tool/rule/file produced this evidence (e.g. a rule xml_id, a model.method, an ORM model+domain)",
    )
    scope: dict[str, Any] = Field(
        default_factory=dict,
        description="Context under which the claim holds: company_id, read_at, execution_identity, plus tool-specific keys.",
    )


def make_evidence(
    source_type: EvidenceSourceType,
    claim: str,
    source: str,
    value: Any = None,
    scope: dict[str, Any] | None = None,
) -> Evidence:
    """Build an Evidence and compute its evidence_id."""
    scope = scope or {}
    return Evidence(
        evidence_id=stable_content_hash(source_type, claim, value, source, scope),
        source_type=source_type,
        claim=claim,
        value=value,
        source=source,
        scope=scope,
    )
