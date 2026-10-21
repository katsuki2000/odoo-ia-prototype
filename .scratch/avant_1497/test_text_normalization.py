import pytest

from code_intelligence.agent.text_normalization import normalize_query_text


@pytest.mark.parametrize("apostrophe", ["\u2019", "\u2018", "\u02bc"])
def test_typographic_apostrophes_fold_to_ascii(apostrophe):
    assert normalize_query_text(f"commande d{apostrophe}achat") == "commande d'achat"


def test_normalization_keeps_accents_composed():
    decomposed = "e\u0301criture d\u2019achat"
    assert normalize_query_text(decomposed) == "\u00e9criture d'achat"
