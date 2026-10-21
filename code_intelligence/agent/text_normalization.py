"""Query text normalization shared by the resolution steps."""

import unicodedata

_TYPOGRAPHIC_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'"})


def normalize_query_text(text: str) -> str:
    """Apply Unicode NFC and fold typographic apostrophes to ASCII."""
    return unicodedata.normalize("NFC", text).translate(_TYPOGRAPHIC_APOSTROPHES)


def strip_accents(text: str) -> str:
    """Remove diacritics (accents) from text, for matching only.

    Apply it to the text being compared, never to text returned to the user: an
    extracted UI label or a graph label must keep its original spelling. Questions
    and instance labels mix accented and unaccented spellings, and NFD-decomposed
    copy-paste or non-French keyboards produce more variants.
    """
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
