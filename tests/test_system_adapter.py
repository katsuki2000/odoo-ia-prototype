"""Hermetic tests for the system response adapter."""

from core.evaluation import frozen_cases as fc
from core.evaluation import system_adapter as sa
from tests.frozen_case_samples import make_case

CASE = fc.FrozenCase.from_dict(make_case("c1"))


def test_classify_outcome():
    assert sa.classify_outcome({"answer": "ok"}) == "answered"
    assert sa.classify_outcome({"error": "boom"}) == "error"
    assert sa.classify_outcome({"answer": sa.INTERNAL_ERROR_MESSAGE}) == "error"
    assert sa.classify_outcome({"answer": "x", "omitted_for_authorization": [{"what": "y"}]}) == "refusal"
    assert sa.classify_outcome({"answer": sa.REFUSAL_MESSAGES[0]}) == "refusal"
    assert sa.classify_outcome({"answer": "x", "ci_evidence_sufficiency": {"status": "insufficient"}}) == "abstention"
    assert sa.classify_outcome({"answer": "x", "ci_evidence_sufficiency": {"status": "sufficient"}}) == "answered"
    assert sa.classify_outcome({"answer": "x", "ci_evidence_sufficiency": {"status": "conflicting"}}) == "answered"


def test_abstention_uses_the_value_the_system_really_serialises():
    from core.evidence.evidence_sufficiency import EvidenceSufficiencyStatus

    raw = {"answer": "x", "ci_evidence_sufficiency": {"status": EvidenceSufficiencyStatus.INSUFFICIENT.value}}
    assert sa.classify_outcome(raw) == "abstention"


def test_rag_fallback_answer_is_not_an_abstention():
    raw = {"answer": "x", "rag_fallback": True, "ci_evidence_sufficiency": {"status": "insufficient"}}
    assert sa.classify_outcome(raw) == "answered"


def test_sources_objects_and_evidence_mapping():
    raw = {
        "answer": "A sales manager can read a quotation.",
        "route": "hybride",
        "resolved_concept": {"is_resolved": True, "resolved_models": ["sale.order"], "resolved_modules": ["sale"]},
        "evidence_dossier": [
            {"source_type": "code", "source": "model:sale.order"},
            {"source_type": "orm", "source": "sale.order"},
            {"source_type": "other", "source": "ignored"},
        ],
        "sources": [{"source": "guide.pdf"}],
    }
    result = sa.to_case_result(CASE, raw)
    assert result.sources_used == ("runtime", "internal_docs")
    assert result.resolved_objects == ("model:sale.order", "module:sale")
    assert result.evidence == (("graph", "model:sale.order"), ("orm", "sale.order"), ("document", "guide.pdf"))
    assert result.claims_total == 0
    assert result.unsupported_claims == 0


def test_unresolved_concept_yields_no_objects():
    assert sa.resolved_objects({"resolved_concept": {"is_resolved": False, "resolved_models": ["x.y"]}}) == ()
    assert sa.resolved_objects({}) == ()
    assert sa.sources_used({"route": "unknown"}) == ()


def test_claim_counts_from_verification_mapping():
    raw = {
        "answer": "ok",
        "verification": {"claims_total": 4, "unsupported_claims": 1},
    }
    result = sa.to_case_result(CASE, raw)
    assert result.claims_total == 4
    assert result.unsupported_claims == 1


def test_claim_counts_from_verification_report_object():
    from core.verification.claims import VerificationReport, VerifierMode

    report = VerificationReport(
        mode=VerifierMode.REPORT,
        claims_total=3,
        unsupported_claims=1,
    )
    raw = {"answer": "ok", "verification": report}
    result = sa.to_case_result(CASE, raw)
    assert result.claims_total == 3
    assert result.unsupported_claims == 1


def test_claim_counts_fallback_and_none():
    assert sa.claim_counts({}) == (0, 0)
    assert sa.claim_counts({"verification": None}) == (0, 0)
    assert sa.claim_counts({"claims_total": 2, "unsupported_claims": 1}) == (2, 1)

