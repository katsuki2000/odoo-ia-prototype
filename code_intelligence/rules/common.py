"""
code_intelligence/deterministic/common.py

Shared constants and enums for deterministic knowledge graph queries.
"""

from enum import Enum

NOT_FOUND_MARKER = "was not found in the indexed knowledge graph"
NO_WORKFLOW_TRANSITION_MARKER = "No workflow state transition could be derived from the indexed code"


class QueryStatus(Enum):
    FOUND = "found"
    EMPTY = "empty"
    NOT_FOUND = "not_found"


def _bold_span_word_count(text: str, delim_pos: int) -> int:
    occurrences_before = text.count("**", 0, delim_pos)
    if occurrences_before % 2 == 0:
        close = text.find("**", delim_pos + 2)
        if close == -1:
            return 0
        content = text[delim_pos + 2:close]
    else:
        open_ = text.rfind("**", 0, delim_pos)
        if open_ == -1:
            return 0
        content = text[open_ + 2:delim_pos]
    return len(content.split())


# Below this word count a bold span is inline emphasis on a term, not a clause boundary.
_BOLD_CLAUSE_MIN_WORDS = 3


def _real_sentence_boundary_before(text: str, pos: int) -> int:
    """Index of the start of the sentence containing text[pos], scanning
    backward. A '.' is a boundary only if followed by whitespace or end-of-
    string (never if immediately followed by an identifier character, e.g.
    the '.' inside 'sale.order'). A '\n' is always a boundary. A '**'
    (Markdown bold delimiter) is a boundary only when it delimits a
    multi-word bold span; a single bold word is inline emphasis and
    scanning continues through it. Falls back to 0 (start of text) if no
    boundary is found."""
    i = pos
    j = 0
    while i > 0:
        i -= 1
        ch = text[i]
        if ch == "\n":
            j = i + 1
            break
        if text[i:i + 2] == "**" and _bold_span_word_count(text, i) >= _BOLD_CLAUSE_MIN_WORDS:
            j = i + 2
            break
        if ch == ".":
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if nxt == "" or nxt.isspace():
                j = i + 1
                break
    else:
        j = 0
    while j < len(text) and text[j] in " \t":
        j += 1
    return j


def _real_sentence_boundary_after(text: str, pos: int) -> int:
    """Index one-past-the-end of the sentence containing text[pos],
    scanning forward. Same boundary rules as _real_sentence_boundary_before
    (a '.' counts only if followed by whitespace/end-of-string; a '\n'
    always counts; a '**' counts only when it delimits a multi-word bold
    span). Falls back to len(text) if no boundary is found."""
    i = pos
    n = len(text)
    while i < n:
        if text[i] == "\n":
            return i
        if text[i:i + 2] == "**" and _bold_span_word_count(text, i) >= _BOLD_CLAUSE_MIN_WORDS:
            return i
        if text[i] == ".":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt == "" or nxt.isspace():
                return i + 1
        i += 1
    return n


def expand_to_sentence_bounds(text: str, start: int, end: int) -> tuple:
    """Expand a regex match span (start, end) outward to the real-sentence
    boundaries of the surrounding text, so a denial-sentence guard swaps a
    complete clause: never a dangling verb/subject stem before it, and never
    the internal '.' of a dotted Odoo identifier mistaken for a sentence end."""
    return _real_sentence_boundary_before(text, start), _real_sentence_boundary_after(text, end)
