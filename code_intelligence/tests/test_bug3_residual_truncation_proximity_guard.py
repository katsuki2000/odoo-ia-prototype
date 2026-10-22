"""
Tests for the bounded correctif mandated in todo/contexte.txt section 504-505
(Bug 3 residual risk, option (b)): any regex-extraction match whose span sits
near a _TRUNCATION_MARKER occurrence in the same text must be rejected rather
than backfilled/relied upon as a fully-grounded deterministic fact.

This is DISTINCT from test_bug3_truncate_observation_boundary.py (sections
500-502), which covers _truncate_observation() itself never splitting a
token mid-word. This suite covers the separate, narrower residual risk
identified in section 503: a token can be complete and real, cut cleanly at
a word/line boundary, while the CONDITION/CONTEXT surrounding it is still
incomplete because the cut landed nearby.
"""


from code_intelligence.agent.context import _TRUNCATION_MARKER
from code_intelligence.utils import _match_near_truncation
from code_intelligence.rules.overrides import _extract_override_chain_amounts


# ── _match_near_truncation itself ────────────────────────────────────────

def test_match_near_truncation_true_when_marker_immediately_follows():
    text = "rec.amount_total > 5000" + _TRUNCATION_MARKER
    start, end = 18, 24  # span of "> 5000" roughly, doesn't need to be exact
    assert _match_near_truncation(text, start, end) is True


def test_match_near_truncation_false_when_marker_far_away():
    filler = "x" * 500
    text = "rec.amount_total > 5000" + filler + _TRUNCATION_MARKER
    assert _match_near_truncation(text, 18, 24) is False


def test_match_near_truncation_false_when_no_marker_at_all():
    text = "rec.amount_total > 5000 and not rec.partner_id.avoir_vip_exempt"
    assert _match_near_truncation(text, 18, 24) is False


# ── _extract_override_chain_amounts (ci_override_cascade.py) ────────────

def test_override_chain_amount_rejected_when_adjacent_to_truncation_marker():
    raw = 'VERROU: "..." (condition : rec.amount_total > 5000' + _TRUNCATION_MARKER
    assert _extract_override_chain_amounts(raw) == []


def test_override_chain_amount_extracted_when_far_from_truncation_marker():
    filler = "x" * 500
    raw = (
        'VERROU: "..." (condition : rec.amount_total > 5000)\n\n'
        + filler
        + _TRUNCATION_MARKER
    )
    assert _extract_override_chain_amounts(raw) == ["5000"]


def test_override_chain_amount_extracted_when_no_truncation_present():
    raw = 'VERROU: "..." (condition : rec.amount_total > 5000)'
    assert _extract_override_chain_amounts(raw) == ["5000"]
