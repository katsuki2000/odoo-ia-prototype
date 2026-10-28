"""
Unit tests of the degenerate-repetition detectors and strippers (core.output).
"""
from core.graph.graph import _detect_degenerate_repetition, _strip_degenerate_repetition


def test_detects_repeated_multiword_phrase():
    """Reproduces the actual Q1.1 shape: a 2-word phrase repeated ~140x."""
    text = (
        "L'utilisateur peut approuver l'avoir sous r\u00e9serve d'appartenir au groupe "
        + "Accountant Manager, " * 140
        + "et de respecter le seuil r\u00e9glementaire.\n\n[Source: Graphe de Connaissances Code Intelligence]"
    )
    assert _detect_degenerate_repetition(text) is True


def test_detects_repeated_single_word():
    text = "Statut : " + "Manager " * 20 + "confirm\u00e9."
    assert _detect_degenerate_repetition(text) is True


def test_normal_prose_reusing_a_term_is_not_flagged():
    """A technical term appearing multiple times across a long, varied
    answer (normal, expected usage) must NOT be flagged -- only immediate,
    consecutive repetition is degenerate."""
    text = (
        "Le groupe Accountant Manager peut approuver les avoirs jusqu'\u00e0 25 000\u20ac. "
        "Au-del\u00e0 de ce montant, seul le groupe Accountant Manager r\u00e9gional combin\u00e9 "
        "avec une validation N+2 permet l'approbation. Le r\u00f4le du Accountant Manager "
        "est donc central dans ce processus, mais toujours born\u00e9 par le seuil."
    )
    assert _detect_degenerate_repetition(text) is False


def test_short_normal_answer_is_not_flagged():
    assert _detect_degenerate_repetition("Oui, l'utilisateur peut voir cet enregistrement.") is False


def test_empty_text_is_not_flagged():
    assert _detect_degenerate_repetition("") is False
    assert _detect_degenerate_repetition(None) is False


def test_strip_collapses_repeated_run_to_single_occurrence():
    text = "Groupe requis : " + "Accountant Manager, " * 140 + "confirm\u00e9."
    stripped = _strip_degenerate_repetition(text)
    assert _detect_degenerate_repetition(stripped) is False
    assert stripped.count("Accountant Manager") == 1
    assert stripped.startswith("Groupe requis : Accountant Manager")
    assert stripped.endswith("confirm\u00e9.")


def test_strip_is_a_no_op_on_clean_text():
    text = "Le groupe Accountant Manager peut approuver cet avoir."
    assert _strip_degenerate_repetition(text) == text
