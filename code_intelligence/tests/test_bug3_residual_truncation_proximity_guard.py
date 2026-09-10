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

import pytest

from code_intelligence.ci_agent_node.prompt_and_heuristics import _TRUNCATION_MARKER
from code_intelligence.answer_text_signals import _match_near_truncation
from code_intelligence.security.locks import (
    _extract_security_lock_condition_amounts,
    _correct_security_lock_threshold_contradictions,
    _SECURITY_LOCK_MESSAGES_MARKER,
)
from code_intelligence.ci_agent_node.access_guards import _extract_required_groups_for_amount
from code_intelligence.overrides import _extract_override_chain_amounts


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


# ── _extract_security_lock_condition_amounts (ci_helpers.py) ────────────

def test_security_lock_amount_rejected_when_adjacent_to_truncation_marker():
    raw = (
        f"{_SECURITY_LOCK_MESSAGES_MARKER}\n"
        "* \"Seuil dépassé\" (condition : rec.amount_total > 5000"
        + _TRUNCATION_MARKER
    )
    assert _extract_security_lock_condition_amounts(raw) == []


def test_security_lock_amount_extracted_when_far_from_truncation_marker():
    filler = "y" * 500
    raw = (
        f"{_SECURITY_LOCK_MESSAGES_MARKER}\n"
        "* \"Seuil dépassé\" (condition : rec.amount_total > 5000)\n"
        + filler
        + _TRUNCATION_MARKER
    )
    assert _extract_security_lock_condition_amounts(raw) == ["5000"]


# ── _extract_required_groups_for_amount (ci_helpers.py) ─────────────────
# A condition line whose match sits near the marker is treated as
# unconditional (same conservative default the function already documents
# for genuinely unconditional locks) -- the group is always retained rather
# than filtered by a threshold read off a possibly-incomplete condition.

def test_required_group_kept_unconditionally_when_condition_near_truncation():
    raw = (
        "Groupe(s) technique(s) requis detecte(s) (has_group): account.group_account_manager\n"
        '* "Seuil" (condition : rec.amount_total > 5000 and has_group(\'account.group_account_manager\')'
        + _TRUNCATION_MARKER
    )
    # amount below the (possibly-real) threshold -- if the truncated
    # condition were trusted, the group would be filtered OUT here; the
    # guard instead keeps it (unconditional fallback).
    result = _extract_required_groups_for_amount(raw, amount=100.0)
    assert result == ["account.group_account_manager"]


def test_required_group_filtered_normally_when_condition_far_from_truncation():
    filler = "z" * 500
    raw = (
        "Groupe(s) technique(s) requis detecte(s) (has_group): account.group_account_manager\n"
        '* "Seuil" (condition : rec.amount_total > 5000 and has_group(\'account.group_account_manager\'))\n'
        + filler
        + _TRUNCATION_MARKER
    )
    # amount below threshold, condition is intact and far from the marker
    # -- normal filtering applies, group is NOT required.
    result = _extract_required_groups_for_amount(raw, amount=100.0)
    assert result == []


# ── _correct_security_lock_threshold_contradictions (ci_helpers.py) ─────
# A condition line near the marker must not be used to "correct" the
# synthesis prose -- no rules collected from it means no contradiction can
# be detected/replaced from that (possibly-incomplete) condition.

def test_no_correction_applied_when_condition_line_near_truncation():
    scoped = (
        '* "Seuil dépassé" (condition : rec.amount_total > 5000 and has_group(\'account.group_account_manager\')'
        + _TRUNCATION_MARKER
    )
    final_answer = (
        "Le comptable n'a pas le permission de valider ce document de 6000€."
    )
    result = _correct_security_lock_threshold_contradictions(
        final_answer, scoped, "Peut-on valider un avoir de 6000€ ?"
    )
    # No-op: the only condition line found was near the truncation marker
    # and was excluded from `rules`, so there is nothing to contradict/correct.
    assert result == final_answer
