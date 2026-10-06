import logging
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


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
            logger.warning(
                "Unknown ANSWER_VERIFIER_MODE %r -- falling back to '%s'.",
                value, cls.REPORT.value,
            )
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
    claims_by_type: Dict[ClaimType, int] = Field(default_factory=dict)
    unsupported_by_type: Dict[ClaimType, int] = Field(default_factory=dict)
    unsupported: List[UnsupportedClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unsupported_within_total(self) -> "VerificationReport":
        if self.unsupported_claims > self.claims_total:
            raise ValueError("unsupported_claims cannot exceed claims_total")
        return self
