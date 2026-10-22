"""Tests for bold-clause recognition in shared sentence-boundary handling."""

from code_intelligence.rules.common import (
    _bold_span_word_count,
    expand_to_sentence_bounds,
)


def test_bold_span_word_count_single_word():
    text = "est **declare** obligatoire"
    open_pos = text.index("**")
    assert _bold_span_word_count(text, open_pos) == 1


def test_bold_span_word_count_multi_word_clause():
    text = "**account.move est un nouveau modele**"
    assert _bold_span_word_count(text, 0) == 5


def test_bold_span_word_count_from_closing_delimiter_position():
    # Called from the CLOSING delimiter's position (odd occurrence count
    # before it) must find the matching opening delimiter backward and
    # return the same word count as when called from the opening one.
    text = "est **declare** obligatoire"
    close_pos = text.index("**", text.index("**") + 2)
    assert _bold_span_word_count(text, close_pos) == 1


def test_bold_span_word_count_no_matching_delimiter_returns_zero():
    text = "un seul ** delimiteur solitaire"
    assert _bold_span_word_count(text, text.index("**")) == 0


def test_single_bold_word_is_not_a_sentence_boundary():
    # No '.' or '\n' anywhere -- if the single bold word wrongly counted as
    # a boundary, expansion would stop right at/after it instead of
    # reaching the true text edges.
    text = "Cette valeur est **declaree** obligatoire par la contrainte"
    start_word = text.index("obligatoire")
    start, end = expand_to_sentence_bounds(text, start_word, start_word + len("obligatoire"))
    assert start == 0
    assert end == len(text)


def test_multi_word_bold_clause_is_still_a_sentence_boundary_844_no_regression():
    # Section 844's own case must still work: a multi-word bold clause
    # joined by "et" to a second bold clause, no '.' or '\n' between them --
    # the first (correct) clause must stay outside the replaced span.
    text = (
        "En resume, **account.move est un nouveau modele cree par le "
        "module account** et **le module ne s'etend pas hors de son "
        "perimetre comptable**."
    )
    start_word = text.index("ne s'etend pas")
    end_word = start_word + len("ne s'etend pas hors de son perimetre comptable")
    start, end = expand_to_sentence_bounds(text, start_word, end_word)
    assert "account.move est un nouveau modele" not in text[start:end]
    assert "cree par le module account" not in text[start:end]
