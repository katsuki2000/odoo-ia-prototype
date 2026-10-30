"""
core/verification/

Deterministic answer verification: no LLM,
claims are extracted by lexical form and checked against tool evidence and the code graph.
"""

from core.schemas import ClaimType, UnsupportedClaim, VerificationReport, VerifierMode

__all__ = ["ClaimType", "UnsupportedClaim", "VerificationReport", "VerifierMode"]
