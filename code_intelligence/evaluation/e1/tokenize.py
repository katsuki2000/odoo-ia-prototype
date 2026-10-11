"""Shared Unicode tokenization for E1 card text and BM25 queries."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[^\W_]+", normalize_text(value), flags=re.UNICODE) if len(token) > 1]
