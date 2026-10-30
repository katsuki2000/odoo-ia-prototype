"""Sentence boundaries of an answer, used to replace a whole clause when a claim is rejected."""

# Below this word count a bold span is inline emphasis on a term, not a clause boundary.
_BOLD_CLAUSE_MIN_WORDS = 3


def _bold_span_word_count(text: str, delimiter_pos: int) -> int:
    if text.count("**", 0, delimiter_pos) % 2 == 0:
        start, end = delimiter_pos + 2, text.find("**", delimiter_pos + 2)
    else:
        start, end = text.rfind("**", 0, delimiter_pos) + 2, delimiter_pos
    return len(text[start:end].split()) if end >= 0 else 0


def _delimiter_at(text: str, i: int) -> str | None:
    """The clause delimiter starting at i: a line break, a multi-word bold marker, or a period ending a sentence
    (never the period inside an identifier such as 'sale.order')."""
    if text[i] == "\n":
        return "\n"
    if text.startswith("**", i) and _bold_span_word_count(text, i) >= _BOLD_CLAUSE_MIN_WORDS:
        return "**"
    if text[i] == "." and text[i + 1:i + 2].strip() == "":
        return "."
    return None


def _sentence_start(text: str, pos: int) -> int:
    start = next(
        (i + len(delimiter) for i in range(pos - 1, -1, -1) if (delimiter := _delimiter_at(text, i))),
        0,
    )
    while start < len(text) and text[start] in " \t":
        start += 1
    return start


def _sentence_end(text: str, pos: int) -> int:
    for i in range(pos, len(text)):
        delimiter = _delimiter_at(text, i)
        if delimiter:
            return i + 1 if delimiter == "." else i
    return len(text)


def expand_to_sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Expand a match span outward to the surrounding sentence, so a whole clause is replaced."""
    return _sentence_start(text, start), _sentence_end(text, end)
