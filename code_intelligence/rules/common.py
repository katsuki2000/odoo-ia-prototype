"""
code_intelligence/deterministic/common.py

Shared constants and enums for deterministic knowledge graph queries.
"""

from enum import Enum

NOT_FOUND_MARKER = "was not found in the indexed knowledge graph"


class QueryStatus(Enum):
    FOUND = "found"
    EMPTY = "empty"
    NOT_FOUND = "not_found"


# todo/contexte.txt sections 840-842: a denial-sentence guard (structure.py's
# module-extension guard, overrides.py's override-count/short-circuit guards)
# locates a fixed negation phrase inside final_answer and swaps it out for a
# corrective sentence built from real tool evidence. Two independent bugs
# were found in how the SPAN to replace gets decided, one in each file:
#   - section 840 (structure.py): an unbounded `[^.\n]*` backward-scan prefix
#     stops at the FIRST '.' it meets scanning backward, including one that
#     is only part of a dotted Odoo identifier ("account.move", "sale.order")
#     rather than a real sentence end -- swallowing whatever correct text
#     sits between that identifier and the actual negation into the replaced
#     span.
#   - section 841 (structure.py, discovered fixing 840): once that unbounded
#     prefix is removed, the match starts exactly at the negation fragment
#     (e.g. "pas d'une extension ... perimetre"), correctly touching nothing
#     before it -- but the fragment then gets swapped for a REPLACEMENT that
#     is itself a standalone sentence ("En realite, ..."), leaving whatever
#     verb/subject introduced the negation ("il ne s'agit ") dangling right
#     before it with no object anymore -- grammatically broken text.
#   - section 842 (overrides.py): the existing `_OVERRIDE_COUNT_DENIAL_RE`
#     avoids the section-841 problem (it already replaces a full standalone
#     sentence via its own unbounded `[^.\n]*` prefix) but reproduces the
#     exact section-840 problem instead -- confirmed by direct reproduction,
#     latent, never triggered in practice, but structurally identical.
# No existing regex-only approach satisfies both constraints at once (full-
# sentence replacement, insensitive to a dotted identifier's internal '.'),
# so this shared helper expands an already-located match span outward to
# real sentence boundaries -- a '.' counts as a boundary only when followed
# by whitespace/end-of-string (never when immediately followed by an
# identifier character, which is what a dotted Odoo name's internal '.'
# always is) -- and a '\n' always counts as a hard boundary (never crossed).
# Both structure.py and overrides.py apply this to their own core negation-
# phrase regex instead of maintaining their own ad hoc backward-scan prefix.
#
# todo/contexte.txt section 844: a further case (test added in section 843
# while adding coverage for expand_to_sentence_bounds itself, pre-existing
# since 840) exposed a genuine trade-off rather than a bug -- a real single
# sentence with two **bold**-marked clauses joined by "et", no '.' or '\n'
# between them ("En resume, **account.move est un nouveau modele...** et
# **le module ne s'etend pas...**."). Expanding to the TRUE sentence start
# swallows the first, correct clause into the replaced span along with the
# second, negated one. Arbitrated: refine the boundary rule rather than
# accept the loss -- an unescaped '**' (Markdown bold delimiter) now also
# counts as a boundary, on both sides. This resolves the trade-off for both
# known cases at once: here, the nearest '**' scanning backward from the
# negation is the OPENING delimiter of the clause that contains it, so the
# first (correct) clause -- and the " et " joining them -- stays outside the
# replaced span. In section 841's case ("**Heritage**\n\nil ne s'agit pas
# d'une extension..."), the nearest '**' scanning backward is the CLOSING
# delimiter of an unrelated preceding heading, with nothing but the
# dangling verb itself between the two -- so that verb still ends up
# included, exactly as section 841 already required.


def _real_sentence_boundary_before(text: str, pos: int) -> int:
    """Index of the start of the sentence containing text[pos], scanning
    backward. A '.' is a boundary only if followed by whitespace or end-of-
    string (never if immediately followed by an identifier character, e.g.
    the '.' inside 'sale.order'). A '\n' is always a boundary. A '**'
    (Markdown bold delimiter) is always a boundary too (section 844) --
    scanning backward lands on the delimiter's first '*', which is where
    the boundary is placed (text right after the pair is kept). Falls back
    to 0 (start of text) if no boundary is found."""
    i = pos
    j = 0
    while i > 0:
        i -= 1
        ch = text[i]
        if ch == "\n":
            j = i + 1
            break
        if text[i:i + 2] == "**":
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
    always counts; a '**' Markdown bold delimiter always counts too,
    section 844 -- excluded from the span, same as '\n'). Falls back to
    len(text) if no boundary is found."""
    i = pos
    n = len(text)
    while i < n:
        if text[i] == "\n":
            return i
        if text[i:i + 2] == "**":
            return i
        if text[i] == ".":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt == "" or nxt.isspace():
                return i + 1
        i += 1
    return n


def expand_to_sentence_bounds(text: str, start: int, end: int) -> tuple:
    """Expand a regex match span (start, end) outward to the real-sentence
    boundaries (see _real_sentence_boundary_before/_after) of the text
    surrounding it, so a denial-sentence guard's replacement always swaps a
    complete clause -- never leaving a dangling verb/subject stem before it
    (todo/contexte.txt section 841), and never mistaking a dotted Odoo
    identifier's internal '.' for a sentence end (section 840/842)."""
    return _real_sentence_boundary_before(text, start), _real_sentence_boundary_after(text, end)
