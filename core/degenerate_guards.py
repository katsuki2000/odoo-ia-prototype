"""
Degenerate-repetition detection and collapsing guards.
"""

import re
from collections import Counter


_DEGENERATE_REPETITION_RE = re.compile(r"\b(\w+(?:\s+\w+){0,2})\b(?:[\s,.-]+\1\b){5,}", re.IGNORECASE)


def _detect_degenerate_repetition(text: str) -> bool:
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
    if not text:
        return False
    return bool(_DEGENERATE_BLANK_RUN_RE.search(text))


def _strip_degenerate_blank_run(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


_DEGENERATE_PREFIX_LENGTH = 60
_DEGENERATE_PREFIX_MIN_REPEATS = 4


def _detect_degenerate_growing_repetition(text: str) -> bool:
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

