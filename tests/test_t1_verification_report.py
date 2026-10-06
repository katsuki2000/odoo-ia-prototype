import logging

import pytest
from pydantic import ValidationError

from core.schemas import AssistantResponse
from core.verification.claims import (
    ClaimType,
    UnsupportedClaim,
    VerificationReport,
    VerifierMode,
)


@pytest.mark.parametrize("raw, expected", [
    ("off", VerifierMode.OFF),
    ("report", VerifierMode.REPORT),
    ("enforce", VerifierMode.ENFORCE),
    ("  ENFORCE ", VerifierMode.ENFORCE),
])
def test_parse_known_values(raw, expected):
    assert VerifierMode.parse(raw) is expected


@pytest.mark.parametrize("raw", ["", "strict", None])
def test_parse_unknown_value_falls_back_to_report(raw, caplog):
    with caplog.at_level(logging.WARNING):
        assert VerifierMode.parse(raw) is VerifierMode.REPORT
    assert "ANSWER_VERIFIER_MODE" in caplog.text


def test_report_defaults_are_empty():
    report = VerificationReport(mode=VerifierMode.REPORT)
    assert report.claims_total == 0
    assert report.unsupported_claims == 0
    assert report.unsupported == []


def test_report_rejects_more_unsupported_than_total():
    with pytest.raises(ValidationError):
        VerificationReport(mode=VerifierMode.REPORT, claims_total=1, unsupported_claims=2)


def test_report_rejects_negative_counts():
    with pytest.raises(ValidationError):
        VerificationReport(mode=VerifierMode.REPORT, claims_total=-1)


def test_assistant_response_verification_is_optional():
    response = AssistantResponse(answer="ok", confidence=1.0)
    assert response.verification is None


def test_assistant_response_dump_exposes_the_counters():
    report = VerificationReport(
        mode=VerifierMode.REPORT,
        claims_total=3,
        unsupported_claims=1,
        claims_by_type={ClaimType.NUMBER: 2, ClaimType.GROUP: 1},
        unsupported_by_type={ClaimType.NUMBER: 1},
        unsupported=[UnsupportedClaim(claim_type=ClaimType.NUMBER, text="12 500", reason="no matching value")],
    )
    dumped = AssistantResponse(answer="ok", confidence=1.0, verification=report).model_dump(mode="json")["verification"]
    assert dumped["claims_total"] == 3
    assert dumped["unsupported_claims"] == 1
    assert dumped["mode"] == "report"
    assert dumped["unsupported_by_type"] == {"number": 1}
    assert dumped["unsupported"][0]["claim_type"] == "number"
