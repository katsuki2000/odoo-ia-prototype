import re

from core.schemas import ClaimType
from core.verification.context import VerificationContext
from core.verification.extractors import Claim

REASON_NO_MATCHING_VALUE = "no_matching_value"
REASON_NOT_IN_EVIDENCE = "not_in_evidence"
REASON_UNKNOWN_METHOD = "unknown_method"


def _contains_token(text: str, token: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text) is not None


def check_number(claim: Claim, context: VerificationContext) -> str | None:
    for reading in claim.readings:
        tolerance = 0.5 * 10 ** -reading.decimals + 1e-9
        if any(abs(reading.value - known) <= tolerance for known in context.evidence_numbers):
            return None
    return REASON_NO_MATCHING_VALUE


def check_group(claim: Claim, context: VerificationContext) -> str | None:
    if _contains_token(context.evidence_text, claim.key):
        return None
    return REASON_NOT_IN_EVIDENCE


def check_method(claim: Claim, context: VerificationContext) -> str | None:
    if claim.name in context.native_method_names:
        return None
    if _contains_token(context.evidence_text, claim.name):
        return None
    return REASON_UNKNOWN_METHOD


CHECKERS = {
    ClaimType.NUMBER: check_number,
    ClaimType.GROUP: check_group,
    ClaimType.METHOD: check_method,
}
