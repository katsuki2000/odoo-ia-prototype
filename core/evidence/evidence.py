"""
core/evidence.py

Evidence is the internal reasoning/provenance object produced directly by Code Intelligence (static
graph analysis) and ORM (live Odoo reads) tools. It lives alongside
SourceReference (core/schemas.py), not instead of it -- SourceReference
stays the UI-facing citation derived later for display, Evidence is the
structured fact a tool produced while it worked.
"""

import hashlib
import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSourceType(str, Enum):
    CODE = "code"
    ORM = "orm"


def _canonical_json(value: Any) -> str:
    """
    Stable JSON serialization used as input to stable_content_hash(). Sorted
    keys and compact separators so two semantically identical dicts/lists
    always serialize identically regardless of construction order.
    default=str covers non-JSON-native types (e.g. a datetime in a scope's
    read_at) via their str/ISO representation, so an Evidence built from a
    datetime object and one built from the equivalent ISO string still hash
    the same.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_content_hash(
    source_type: EvidenceSourceType,
    claim: str,
    value: Any,
    source: str,
    scope: dict[str, Any],
) -> str:
    """
    Deterministic evidence_id: the same fact reported twice (by CI and ORM
    on the same underlying truth, or by the same tool across two runs)
    hashes to the same id, enabling dedup at the Evidence Builder level
    instead of listing the same fact twice. SHA-256 truncated to 32 hex
    chars -- long enough that accidental collision within a single
    investigation's evidence set is not a practical concern, short enough
    to stay readable in traces and tests.
    """
    payload = _canonical_json({
        "source_type": source_type.value,
        "claim": claim,
        "value": value,
        "source": source,
        "scope": scope,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class Evidence(BaseModel):
    """
    Internal reasoning/provenance contract shared by Code Intelligence and
    ORM tools. Distinct from SourceReference: Evidence is what a tool
    actually produced (fact + provenance), SourceReference is how a fact
    gets displayed in the UI.
    """
    model_config = ConfigDict(strict=True)

    evidence_id: str = Field(
        ..., description="stable_content_hash() of this evidence's canonical payload"
    )
    source_type: EvidenceSourceType
    claim: str = Field(..., description="What this evidence asserts, in plain language")
    value: Any = Field(default=None, description="The concrete fact/value backing the claim")
    source: str = Field(
        ...,
        description=(
            "Which tool/rule/file produced this evidence "
            "(e.g. a rule xml_id, a model.method, an ORM model+domain)"
        ),
    )
    confidence: Optional[str] = Field(
        default=None,
        description=(
            "Epistemic uncertainty on a CI static/heuristic reading (e.g. "
            "HIGH/MEDIUM/LOW). Never set for a deterministic ORM read -- "
            "use scope instead, ORM correctness-in-context is a different "
            "axis than certainty."
        ),
    )
    scope: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Context under which value/claim holds. Canonical keys: "
            "company_id, read_at, execution_identity. Additional keys "
            "(record_ids, model, date_from, date_to, ...) are allowed when "
            "a tool has a real need for them, and must be documented where "
            "they are introduced."
        ),
    )


def make_evidence(
    source_type: EvidenceSourceType,
    claim: str,
    source: str,
    value: Any = None,
    confidence: Optional[str] = None,
    scope: Optional[dict[str, Any]] = None,
) -> Evidence:
    """Convenience constructor: computes evidence_id from the canonical
    payload so call sites never hand-roll the hash themselves."""
    scope = scope or {}
    evidence_id = stable_content_hash(source_type, claim, value, source, scope)
    return Evidence(
        evidence_id=evidence_id,
        source_type=source_type,
        claim=claim,
        value=value,
        source=source,
        confidence=confidence,
        scope=scope,
    )
