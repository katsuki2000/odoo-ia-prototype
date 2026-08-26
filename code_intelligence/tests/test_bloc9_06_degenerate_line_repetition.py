"""
miro-rag/code_intelligence/tests/test_bloc9_06_degenerate_line_repetition.py

 gap, module 6/8 (custom_automation_traps, 2026-08-10, ):
locks in the LINE-level degenerate-repetition guard added to rag/graph.py, plus
basic coverage for the pre-existing PHRASE-level guard, which had zero pytest
coverage before this file despite already being live in production.

Live finding: llama-3.1-8b-instant's decoding-collapse failure mode (documented
since the Q1.1 benchmark run as "Accountant Manager" repeated ~140x) recurred in
a NEW shape during  -- not a short repeated phrase this time,
but the same ~40-word bullet line ("- `xml_id: account.group_account_manager` :
Ce groupe est requis...") repeated ~50 times until the response was cut off
mid-word. The existing `_DEGENERATE_REPETITION_RE` regex structurally cannot
catch this (its capture group is capped at a 1-3 word phrase), so the guard
never fired and the wall of repeated text shipped straight through to the
"final_answer". `_detect_degenerate_line_repetition` /
`_strip_degenerate_line_repetition` close that gap at the line granularity;
`_detect_any_degenerate_repetition` / `_strip_any_degenerate_repetition` run
both granularities together, which is what's actually wired into
code_intelligence_agent's three call sites.

No mocks: exercises the real functions directly against realistic text,
including the actual repeated line shape observed live.
"""

from core.graph import (
    _detect_degenerate_repetition,
    _strip_degenerate_repetition,
    _detect_degenerate_line_repetition,
    _strip_degenerate_line_repetition,
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)


# The actual repeated line shape observed live in 06b-technical
# (2026-08-10), verbatim shape (shortened repeat count for test speed --
# the live case repeated it ~50 times, 5 is well past the detection
# threshold of 4).
_REAL_DEGENERATE_LINE = (
    "- `xml_id: account.group_account_manager` : Ce groupe est requis pour "
    "valider un avoir de plus de 5000\u20ac. Cette r\u00e8gle est d\u00e9finie dans le "
    "module `account_move.py` et est \u00e9valu\u00e9e lorsque `rec.amount_total > 5000` "
    "et que l'utilisateur actuel n'appartient pas au groupe "
    "`account.group_account_manager`."
)

_CLEAN_ANSWER = (
    "Seul un responsable comptable (groupe account.group_account_manager) "
    "peut valider un avoir de plus de 5000\u20ac. Cette r\u00e8gle est d\u00e9finie dans "
    "le module custom_credit_note_approval.\n\n[Source: Graphe de Connaissances "
    "Code Intelligence]"
)


class TestDetectDegenerateLineRepetition:
    def test_flags_real_repeated_bullet_line_shape(self):
        """Core regression test: the exact live failure shape from
         must now be caught."""
        text = "\n".join([_REAL_DEGENERATE_LINE] * 5)
        assert _detect_degenerate_line_repetition(text) is True

    def test_below_threshold_repeat_count_not_flagged(self):
        """3 repeats (below the 4-repeat threshold) must not false-positive
        -- a line legitimately restated 2-3 times across a long answer
        (e.g. summarizing then concluding) is normal prose, not a decoding
        collapse."""
        text = "\n".join([_REAL_DEGENERATE_LINE] * 3)
        assert _detect_degenerate_line_repetition(text) is False

    def test_short_repeated_lines_not_flagged(self):
        """Short list items (below the length floor) can legitimately
        repeat across a long list (e.g. a table of short markers) --
        must not be flagged as a decoding collapse."""
        text = "\n".join(["- OK"] * 10)
        assert _detect_degenerate_line_repetition(text) is False

    def test_clean_answer_not_flagged(self):
        assert _detect_degenerate_line_repetition(_CLEAN_ANSWER) is False

    def test_empty_string_not_flagged(self):
        assert _detect_degenerate_line_repetition("") is False


class TestStripDegenerateLineRepetition:
    def test_collapses_repeated_line_to_first_occurrence(self):
        text = "Intro.\n" + "\n".join([_REAL_DEGENERATE_LINE] * 5) + "\nConclusion."
        result = _strip_degenerate_line_repetition(text)
        assert result.count(_REAL_DEGENERATE_LINE) == 1
        # Surrounding non-repeated content is preserved, in order.
        assert result.startswith("Intro.")
        assert result.endswith("Conclusion.")

    def test_short_repeated_lines_are_preserved_not_collapsed(self):
        """Below the length floor, repeats are legitimate list items and
        must survive the strip untouched."""
        text = "\n".join(["- OK"] * 5)
        result = _strip_degenerate_line_repetition(text)
        assert result.count("- OK") == 5

    def test_clean_answer_unchanged(self):
        assert _strip_degenerate_line_repetition(_CLEAN_ANSWER) == _CLEAN_ANSWER


class TestDetectDegenerateRepetitionPhraseLevel:
    """Basic coverage for the pre-existing phrase-level guard -- had zero
    pytest coverage before this file despite being live in production
    since the Q1.1 benchmark finding."""

    def test_flags_short_phrase_repeated_many_times(self):
        text = "Accountant Manager " * 10
        assert _detect_degenerate_repetition(text) is True

    def test_clean_prose_not_flagged(self):
        assert _detect_degenerate_repetition(_CLEAN_ANSWER) is False

    def test_strip_collapses_repeated_phrase(self):
        text = "Accountant Manager " * 10
        result = _strip_degenerate_repetition(text)
        assert result.count("Accountant Manager") == 1

    def test_phrase_level_guard_does_not_catch_full_sentence_repetition(self):
        """Documents the actual gap this session found: the phrase-level
        regex is structurally incapable of catching a repeated FULL
        SENTENCE (well beyond its 3-word capture cap) -- this is exactly
        why the line-level guard above was added as a complement, not a
        replacement."""
        text = "\n".join([_REAL_DEGENERATE_LINE] * 5)
        assert _detect_degenerate_repetition(text) is False


class TestCombinedDegenerateRepetitionGuard:
    """Tests for _detect_any_degenerate_repetition / _strip_any_degenerate_repetition
    -- what's actually wired into code_intelligence_agent's three call sites."""

    def test_catches_phrase_level_case(self):
        text = "Accountant Manager " * 10
        assert _detect_any_degenerate_repetition(text) is True

    def test_catches_line_level_case(self):
        text = "\n".join([_REAL_DEGENERATE_LINE] * 5)
        assert _detect_any_degenerate_repetition(text) is True

    def test_clean_answer_not_flagged(self):
        assert _detect_any_degenerate_repetition(_CLEAN_ANSWER) is False

    def test_strip_handles_both_granularities_in_one_pass(self):
        """A pathological answer degenerate at BOTH granularities at once
        must come out clean after a single combined strip call."""
        text = (
            "Accountant Manager " * 10
            + "\n"
            + "\n".join([_REAL_DEGENERATE_LINE] * 5)
        )
        result = _strip_any_degenerate_repetition(text)
        assert not _detect_any_degenerate_repetition(result)
        assert result.count("Accountant Manager") == 1
        assert result.count(_REAL_DEGENERATE_LINE) == 1
