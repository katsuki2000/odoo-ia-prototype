"""
code_intelligence/tests/test_section922_bold_word_boundary.py

todo/contexte.txt section 921 (STK-Q3/ACC-Q3), fixed in section 922: since
section 844, _real_sentence_boundary_before/_after (common.py) treated
EVERY '**' Markdown bold delimiter as a sentence boundary. That was correct
for 844's own case (a full clause wrapped in "**...**"), but a single bold
WORD embedded mid-sentence ("est **declare** obligatoire") is not a
sentence boundary at all -- treating it as one severed the sentence at the
first bold word, corrupting the module-extension-denial guard's
replacement (STK-Q3: phrase cut mid-flow; ACC-Q3: "- Il **" left orphaned
before a bullet). The fix adds a word-count threshold
(_BOLD_CLAUSE_MIN_WORDS = 3): a '**' pair only counts as a boundary when
the wrapped span has at least that many words -- a genuine clause, not an
inline-emphasized term.
"""

from code_intelligence.rules.common import (
    _bold_span_word_count,
    expand_to_sentence_bounds,
)
from code_intelligence.rules.structure import _neutralize_module_extension_denial


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


def test_neutralize_module_extension_denial_does_not_sever_at_single_bold_word():
    # End-to-end reproduction of the STK-Q3 shape: a single bold word
    # ("declare") sits between the sentence start and the denial phrase.
    # The old behavior treated the bold word's own delimiters as the
    # sentence boundary, leaving a corrupted fragment either side of the
    # replacement. The fix must produce one clean replacement sentence,
    # with nothing torn off before it.
    answer = (
        "Le champ est **declare** obligatoire et le module ne s'etend pas "
        "hors de son perimetre comptable."
    )
    fixed = _neutralize_module_extension_denial(answer, ["stock.quant", "stock.lot"])
    assert "En réalité, ce module étend bien 2 modèle(s)" in fixed
    assert "**declare**" not in fixed
    assert not fixed.rstrip().endswith("**")


def test_neutralize_module_extension_denial_does_not_leave_orphan_bullet_stem():
    # ACC-Q3 shape: "- Il **" left orphaned before the bullet, per section
    # 921's diagnosis.
    answer = (
        "- Il **declare** que le module ne s'etend pas hors de son "
        "perimetre comptable."
    )
    fixed = _neutralize_module_extension_denial(answer, ["account.move"])
    assert "- Il **" not in fixed
    assert "En réalité, ce module étend bien 1 modèle(s)" in fixed
