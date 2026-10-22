"""Query text normalization shared by the resolution steps."""

import unicodedata

_TYPOGRAPHIC_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'"})


def normalize_query_text(text: str) -> str:
    """Apply Unicode NFC and fold typographic apostrophes to ASCII."""
    return unicodedata.normalize("NFC", text).translate(_TYPOGRAPHIC_APOSTROPHES)


def strip_accents(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
