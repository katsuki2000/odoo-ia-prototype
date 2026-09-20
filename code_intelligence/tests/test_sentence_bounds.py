"""
code_intelligence/tests/test_sentence_bounds.py

todo/contexte.txt section 842 (option 4): isolated unit tests for the shared
sentence-boundary helper used by both structure.py's module-extension-denial
guard (838-841) and overrides.py's override-count/short-circuit-denial
guards (825), so a denial-sentence guard's replacement always swaps a
complete, real sentence -- never stopping at a '.' that is merely part of a
dotted Odoo identifier ("account.move", "sale.order"), and never leaving a
verb/subject stem dangling immediately before the replacement.
"""

from code_intelligence.rules.common import expand_to_sentence_bounds


def test_dotted_identifier_is_not_treated_as_a_sentence_boundary():
    # "sale.order" contains a literal '.' not followed by whitespace --
    # must be skipped when scanning backward for the real sentence start.
    text = "Le modele cible est sale.order et il n'y a pas de surcharges."
    start_word = text.index("il n'y a pas")
    end_word = start_word + len("il n'y a pas")
    start, end = expand_to_sentence_bounds(text, start_word, end_word)
    assert start == 0
    assert text[start:end] == text


def test_real_period_followed_by_space_is_a_boundary():
    text = "Premiere phrase correcte. Deuxieme phrase avec la negation ici."
    start_word = text.index("la negation")
    end_word = start_word + len("la negation")
    start, end = expand_to_sentence_bounds(text, start_word, end_word)
    assert text[:start] == "Premiere phrase correcte. "
    assert start == len("Premiere phrase correcte. ")


def test_dotted_identifier_in_an_earlier_untouched_sentence_does_not_leak_forward():
    # The internal '.' of "sale.order" sits in a PRIOR sentence, further
    # back than the real period ending that sentence -- the real period
    # must win, and the prior sentence must stay completely untouched.
    text = "Le modele cible est sale.order. En resume, il n'y a pas de surcharges."
    start_word = text.index("il n'y a pas")
    end_word = start_word + len("il n'y a pas")
    start, end = expand_to_sentence_bounds(text, start_word, end_word)
    assert text[:start] == "Le modele cible est sale.order. "
    assert "sale.order" not in text[start:end]


def test_newline_is_always_a_hard_boundary():
    text = "Premiere ligne correcte\nDeuxieme ligne avec negation ici"
    start_word = text.index("negation")
    end_word = start_word + len("negation")
    start, end = expand_to_sentence_bounds(text, start_word, end_word)
    assert start == len("Premiere ligne correcte\n")


def test_falls_back_to_text_start_when_no_boundary_exists():
    text = "negation en tout debut de texte sans aucun point avant"
    start, end = expand_to_sentence_bounds(text, 0, len("negation"))
    assert start == 0


def test_falls_back_to_text_end_when_no_boundary_exists():
    text = "phrase sans point de fin qui continue jusqu'au bout du texte"
    start_word = text.index("continue")
    start, end = expand_to_sentence_bounds(text, start_word, start_word + len("continue"))
    assert end == len(text)
