import logging
import re
from collections import Counter

from core.verification.checkers import CHECKERS
from core.schemas import ClaimType, UnsupportedClaim, VerificationReport, VerifierMode
from core.verification.context import VerificationContext
from core.verification.extractors import SOURCE_FOOTER_RE, SYSTEM_BLOCK_RE, Claim, extract_claims
from core.verification.sentence_bounds import expand_to_sentence_bounds

logger = logging.getLogger(__name__)

RETIREMENT_NOTICE = "[DETERMINISTIC VERIFICATION] Claim(s) removed for lack of evidence in this turn's data: "


def _by_type(claims: list[Claim]) -> dict[ClaimType, int]:
    return dict(Counter(claim.claim_type for claim in claims))


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _with_notice(text: str, notice: str) -> str:
    anchors = [match.start() for match in (SOURCE_FOOTER_RE.search(text), SYSTEM_BLOCK_RE.search(text)) if match]
    if not anchors:
        return text.rstrip() + "\n\n" + notice
    cut = min(anchors)
    return text[:cut].rstrip() + "\n\n" + notice + "\n\n" + text[cut:]


def _retire(answer: str, claims: list[Claim]) -> str:
    spans = _merge_spans([
        expand_to_sentence_bounds(answer, start, end)
        for claim in claims
        for start, end in claim.spans
    ])
    kept, cursor = [], 0
    for start, end in spans:
        kept.append(answer[cursor:start])
        cursor = end
    kept.append(answer[cursor:])
    cleaned = re.sub(r"[ \t]+\n", "\n", "".join(kept))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    texts = ", ".join(dict.fromkeys(claim.text for claim in claims))
    return _with_notice(cleaned, RETIREMENT_NOTICE + texts + ".")


def verify_answer_claims(
    answer: str, context: VerificationContext, mode: VerifierMode,
) -> tuple[str, VerificationReport]:
    if mode is VerifierMode.OFF:
        return answer, VerificationReport(mode=mode)
    claims = extract_claims(answer)
    verdicts = [(claim, CHECKERS[claim.claim_type](claim, context)) for claim in claims]
    unsupported = [(claim, reason) for claim, reason in verdicts if reason]
    report = VerificationReport(
        mode=mode,
        claims_total=len(claims),
        unsupported_claims=len(unsupported),
        claims_by_type=_by_type(claims),
        unsupported_by_type=_by_type([claim for claim, _ in unsupported]),
        unsupported=[
            UnsupportedClaim(claim_type=claim.claim_type, text=claim.text, reason=reason)
            for claim, reason in unsupported
        ],
    )
    if unsupported:
        logger.info(
            "Answer verifier [%s]: %d/%d claims without evidence: %s",
            mode.value, len(unsupported), len(claims),
            ", ".join(f"{claim.claim_type.value}:{claim.text}" for claim, _ in unsupported),
        )
    if mode is VerifierMode.ENFORCE and unsupported:
        answer = _retire(answer, [claim for claim, _ in unsupported])
    return answer, report
