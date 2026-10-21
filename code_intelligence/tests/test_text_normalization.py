import pytest

from code_intelligence.agent.text_normalization import normalize_query_text, strip_accents


@pytest.mark.parametrize("apostrophe", ["\u2019", "\u2018", "\u02bc"])
def test_typographic_apostrophes_fold_to_ascii(apostrophe):
    assert normalize_query_text(f"commande d{apostrophe}achat") == "commande d'achat"


def test_normalization_keeps_accents_composed():
    decomposed = "e\u0301criture d\u2019achat"
    assert normalize_query_text(decomposed) == "\u00e9criture d'achat"


def test_strip_accents_removes_composed_accents():
    assert strip_accents("mise \u00e0 disposition de mat\u00e9riel") == "mise a disposition de materiel"


def test_strip_accents_removes_decomposed_accents():
    assert strip_accents("e\u0301criture d\u2019achat") == "ecriture d\u2019achat"


def test_strip_accents_leaves_ascii_and_empty_text_unchanged():
    assert strip_accents("sale.order") == "sale.order"
    assert strip_accents("") == ""
