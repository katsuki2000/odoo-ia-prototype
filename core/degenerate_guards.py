"""
rag/degenerate_guards.py

Degenerate-repetition detection and collapsing guards.

Small synthesis models (e.g. llama-3.1-8b-instant at temperature=0) occasionally
collapse into decoding loops -- the same word, phrase, line, or blank-line run
repeated dozens of times. These guards detect and strip those patterns as a
last resort before shipping an answer to the user.
"""

import re
from collections import Counter


_DEGENERATE_REPETITION_RE = re.compile(r"\b(\w+(?:\s+\w+){0,2})\b(?:[\s,.-]+\1\b){5,}", re.IGNORECASE)


def _detect_degenerate_repetition(text: str) -> bool:
    """
    Review finding (Q1.1 benchmark run): llama-3.1-8b-instant at
    temperature=0 with no frequency/presence penalty occasionally collapses
    into a decoding loop -- the same word or short phrase repeated dozens
    of times in a row (observed: ~140x "Accountant Manager") -- typically
    right after a truncated tool observation pushes the context close to
    the model's limit. This is not tool output (no '- xxx:' shape), it's a
    synthesis-LLM decoding failure.

    Detects a 1-3 word phrase immediately repeated 6+ times in a row. Kept
    deliberately narrow (consecutive repetition only) to avoid flagging
    normal prose that legitimately reuses a technical term across a long
    answer.
    """
    if not text:
        return False
    return bool(_DEGENERATE_REPETITION_RE.search(text))


def _strip_degenerate_repetition(text: str) -> str:
    """Collapse a detected degenerate run down to a single occurrence of
    the repeated phrase, as a last resort if a retry still comes back
    degenerate -- never ship a wall of repeated tokens to the user."""
    return _DEGENERATE_REPETITION_RE.sub(r"\1", text)


_DEGENERATE_LINE_REPETITION_MIN_REPEATS = 4
_DEGENERATE_LINE_MIN_LENGTH = 30


def _detect_degenerate_line_repetition(text: str) -> bool:
    """
    Second, complementary decoding-collapse detector -- live finding
    (bloc9-06b-technical, 2026-08-10): `_DEGENERATE_REPETITION_RE` above
    only catches a SHORT (1-3 word) phrase repeating consecutively, since
    it was written for the original Q1.1 case ("Accountant Manager" x140).
    It does NOT generalize to a full SENTENCE or bullet line repeating
    verbatim many times, which is exactly the shape observed live: the
    same ~40-word "- `xml_id: account.group_account_manager` : Ce groupe
    est requis..." line repeated ~50 times until the response was cut off
    mid-word. Same underlying model decoding-collapse failure, just at a
    coarser granularity that the phrase-level regex structurally cannot
    catch (its capture group is capped at 3 words).

    Splits the text into lines and flags any single line -- above a
    minimum length, so short legitimately-repeatable list items (e.g. a
    short marker on consecutive bullet rows) don't false-positive -- that
    recurs _DEGENERATE_LINE_REPETITION_MIN_REPEATS+ times anywhere in the
    text (not necessarily contiguously -- a real synthesis answer does not
    legitimately repeat a 30+ character sentence four times regardless of
    spacing, so this is safe to check globally rather than only
    consecutively).
    """
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= _DEGENERATE_LINE_MIN_LENGTH]
    if not lines:
        return False
    counts = Counter(lines)
    return any(c >= _DEGENERATE_LINE_REPETITION_MIN_REPEATS for c in counts.values())


def _strip_degenerate_line_repetition(text: str) -> str:
    """Collapse repeated (near-)identical lines down to their first
    occurrence, preserving original order -- same last-resort philosophy
    as `_strip_degenerate_repetition`, at the coarser line granularity."""
    seen = set()
    out_lines = []
    for line in text.splitlines():
        key = line.strip()
        if len(key) >= _DEGENERATE_LINE_MIN_LENGTH:
            if key in seen:
                continue
            seen.add(key)
        out_lines.append(line)
    return "\n".join(out_lines)


_DEGENERATE_BLANK_RUN_RE = re.compile(r"(?:[ \t]*\n){15,}")


def _detect_degenerate_blank_run(text: str) -> bool:
    """
    Third, complementary decoding-collapse detector -- live finding
    (bloc9-06c-technical-condition-capture, 2026-08-11): neither
    `_detect_degenerate_repetition` (short phrase, 6+ consecutive) nor
    `_detect_degenerate_line_repetition` (a 30+ char line/sentence
    repeated 4+ times ANYWHERE) catches this shape -- the model instead
    collapsed into emitting dozens of consecutive blank/whitespace-only
    lines (observed: ~30+ bare newlines in a row) between two otherwise-
    normal sentences, which is neither a repeated phrase nor a repeated
    non-empty line. `_DEGENERATE_LINE_MIN_LENGTH`'s own 30-char floor
    exists specifically to avoid flagging short legitimate repeated list
    markers -- it also, as a side effect, filters out every blank line
    before `_detect_degenerate_line_repetition` even counts them, so this
    needed its own dedicated detector rather than a threshold tweak to an
    existing one. Same underlying model decoding-collapse failure mode as
    the other two, just manifesting as an absence of content instead of a
    repeated one.

    15+ consecutive blank/whitespace-only lines is far beyond anything a
    real synthesis answer legitimately produces (normal paragraph spacing
    is at most 1-2 blank lines between sections) -- chosen with the same
    "only the clear, unambiguous shape" conservatism as every other
    deterministic check in this module (see e.g. _detect_link_guard_field
    in semgrep_locks_analyzer.py).
    """
    if not text:
        return False
    return bool(_DEGENERATE_BLANK_RUN_RE.search(text))


def _strip_degenerate_blank_run(text: str) -> str:
    """Collapse any run of 3+ consecutive newlines (2+ blank lines) down to
    a single blank line (2 newlines) -- same last-resort philosophy as the
    other two strippers. Deliberately not scoped to only the detected
    15+-line run: a lower-magnitude version of the same collapse (e.g. 4-5
    blank lines) is still visually broken and worth normalizing whenever
    this stripper runs at all, and normal prose never legitimately uses
    more than one blank line for spacing.
    """
    return re.sub(r"\n{3,}", "\n\n", text)


_DEGENERATE_PREFIX_LENGTH = 60
_DEGENERATE_PREFIX_MIN_REPEATS = 4


def _detect_degenerate_growing_repetition(text: str) -> bool:
    """
    Fourth, complementary decoding-collapse detector -- live finding
    (bloc9-06c-technical-condition-capture, 2026-08-13): none of the other
    three catch a SNOWBALLING sentence, where each successive line restates
    the previous one verbatim as a prefix and appends a further clause
    ("Il n'y a pas de restriction ... pour les avoirs qui ne sont pas
    associés à une facture de dépense." then "...et qui ne nécessitent pas
    de mise à jour de la partie commerciale." then a third clause on top of
    that, etc.). Every line is technically unique character-for-character,
    so `_detect_degenerate_line_repetition`'s exact-match Counter never
    trips on it -- but they all share a very long common prefix, which is
    the same underlying decoding-collapse failure mode restating itself
    with growing content instead of identical content.

    Flags when `_DEGENERATE_PREFIX_MIN_REPEATS`+ distinct lines (above the
    same `_DEGENERATE_LINE_MIN_LENGTH` floor as the exact-line detector)
    share an identical first `_DEGENERATE_PREFIX_LENGTH`-character prefix.
    60 chars (vs. the exact-line detector's 30-char minimum LINE length) is
    deliberately longer than a single clause -- keeps this narrow enough
    that legitimate answers with several distinct `[FAIT DÉTERMINISTIQUE]`
    lines (which share only the ~23-char label, not 60 chars of actual
    content) never false-positive; verified functionally against a 4-line
    legitimate fixture before this was wired in.
    """
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= _DEGENERATE_LINE_MIN_LENGTH]
    if not lines:
        return False
    prefixes = Counter(ln[:_DEGENERATE_PREFIX_LENGTH] for ln in lines)
    return any(c >= _DEGENERATE_PREFIX_MIN_REPEATS for c in prefixes.values())


def _strip_degenerate_growing_repetition(text: str) -> str:
    """Collapse a snowballing-sentence run down to its first (shortest)
    occurrence per shared prefix group, same last-resort philosophy as the
    other three strippers."""
    seen_prefixes = set()
    out_lines = []
    for line in text.splitlines():
        key = line.strip()
        if len(key) >= _DEGENERATE_LINE_MIN_LENGTH:
            prefix = key[:_DEGENERATE_PREFIX_LENGTH]
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
        out_lines.append(line)
    return "\n".join(out_lines)


def _detect_any_degenerate_repetition(text: str) -> bool:
    """Combined check -- run all four degenerate-repetition detectors,
    since they catch different granularities of the same underlying
    decoding-collapse failure mode."""
    return (
        _detect_degenerate_repetition(text)
        or _detect_degenerate_line_repetition(text)
        or _detect_degenerate_blank_run(text)
        or _detect_degenerate_growing_repetition(text)
    )


def _strip_any_degenerate_repetition(text: str) -> str:
    """Combined last-resort strip -- apply all four collapsers so no
    granularity of repeated content survives into the shipped answer."""
    return _strip_degenerate_growing_repetition(
        _strip_degenerate_blank_run(_strip_degenerate_line_repetition(_strip_degenerate_repetition(text)))
    )

