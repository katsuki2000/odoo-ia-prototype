"""
core/verification/

Deterministic answer verification (todo/contexte.txt sections 1119-1122): no LLM,
claims are extracted by lexical form and checked against tool evidence and the code graph.
"""

from .claims import ClaimType, UnsupportedClaim, VerificationReport, VerifierMode

__all__ = ["ClaimType", "UnsupportedClaim", "VerificationReport", "VerifierMode"]
