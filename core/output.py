"""
core/output.py

Single source of truth for the French confidence-level word used inside the
"[Confiance: ...]" tag that deterministic/heuristic analyzers (security,
data_constraints, server_actions, overrides) inject verbatim into tool
observation text (schema C, cf. todo/contexte.txt Section 626). Before this
module, each call site hardcoded its own label, mixing English ("HIGH") and
French ("FAIBLE") for the same concept.

Distinct from and does not change:
  - AssistantResponse.confidence (core/schemas.py): float 0.0-1.0, turn-level.
  - The "high"/"medium"/"low" English enum that overrides/server_actions
    LLM interpretation prompts require as their strict JSON output contract
    (schema B) -- that contract is untouched, this module only maps its
    values to a display word.

=== html_sanitizer (ex core/output/html_sanitizer.py) ===

Backend defense against LLM-emitted raw HTML in answer text.
Converts common structural HTML tags back to Markdown equivalents
before the answer reaches the frontend or any API consumer.

=== degenerate_guards (ex core/output/degenerate_guards.py) ===

Degenerate-repetition detection and collapsing guards.
"""

import re
from collections import Counter

# --- confidence_tags -------------------------------------------------------

_CONFIDENCE_LABELS = {
    "high": "ÉLEVÉE",
    "medium": "MOYENNE",
    "low": "FAIBLE",
}


def confidence_label(level: str) -> str:
    """Return the canonical French confidence-level word for a "high"/"medium"/"low" value."""
    try:
        return _CONFIDENCE_LABELS[level.lower()]
    except KeyError:
        raise ValueError(f"Unknown confidence level: {level!r}") from None


# --- html_sanitizer ----------------------------------------------------------

_HEADING_RE = re.compile(
    r'<h([1-6])(?:\s[^>]*)?>(.+?)</h\1>',
    re.IGNORECASE | re.DOTALL,
)

_BOLD_RE = re.compile(r'<strong(?:\s[^>]*)?>(.+?)</strong>', re.IGNORECASE | re.DOTALL)
_ITALIC_RE = re.compile(r'<em(?:\s[^>]*)?>(.+?)</em>', re.IGNORECASE | re.DOTALL)
_BR_RE = re.compile(r'<br\s*/?>',  re.IGNORECASE)

_UL_BLOCK_RE = re.compile(
    r'<ul(?:\s[^>]*)?>(.*?)</ul>',
    re.IGNORECASE | re.DOTALL,
)
_OL_BLOCK_RE = re.compile(
    r'<ol(?:\s[^>]*)?>(.*?)</ol>',
    re.IGNORECASE | re.DOTALL,
)
_LI_RE = re.compile(r'<li(?:\s[^>]*)?>(.*?)</li>', re.IGNORECASE | re.DOTALL)

_P_RE = re.compile(r'<p(?:\s[^>]*)?>(.*?)</p>', re.IGNORECASE | re.DOTALL)
_DIV_RE = re.compile(r'<div(?:\s[^>]*)?>(.*?)</div>', re.IGNORECASE | re.DOTALL)

_LEFTOVER_TAGS_RE = re.compile(r'</?(?:span|a|table|tr|td|th|thead|tbody|blockquote)(?:\s[^>]*)?>', re.IGNORECASE)

_HEADING_LEVEL_MAP = {1: "# ", 2: "## ", 3: "### ", 4: "#### ", 5: "## ", 6: "### "}

_CONSECUTIVE_BLANK_RE = re.compile(r'\n{3,}')


def _convert_ul(match: re.Match) -> str:
    inner = match.group(1)
    items = _LI_RE.findall(inner)
    lines = [f"- {item.strip()}" for item in items]
    return "\n" + "\n".join(lines) + "\n"


def _convert_ol(match: re.Match) -> str:
    inner = match.group(1)
    items = _LI_RE.findall(inner)
    lines = [f"{i + 1}. {item.strip()}" for i, item in enumerate(items)]
    return "\n" + "\n".join(lines) + "\n"


def _convert_heading(match: re.Match) -> str:
    level = int(match.group(1))
    text = match.group(2).strip()
    prefix = _HEADING_LEVEL_MAP.get(level, "### ")
    return f"\n{prefix}{text}\n"


def sanitize_html_to_markdown(text: str) -> str:
    """Convert common HTML tags in LLM output to Markdown equivalents.

    Designed as a backend safety net: if the LLM emits HTML despite the
    prompt contract, this normalizes it to Markdown before the answer
    reaches formatMarkdown() on the frontend (which would otherwise
    escape unrecognized tags into visible &lt;h5&gt; literals).
    """
    if not text or "<" not in text:
        return text

    result = text

    result = _UL_BLOCK_RE.sub(_convert_ul, result)
    result = _OL_BLOCK_RE.sub(_convert_ol, result)
    result = _HEADING_RE.sub(_convert_heading, result)
    result = _BOLD_RE.sub(r"**\1**", result)
    result = _ITALIC_RE.sub(r"*\1*", result)
    result = _BR_RE.sub("\n", result)
    result = _P_RE.sub(r"\1\n\n", result)
    result = _DIV_RE.sub(r"\1\n", result)
    result = _LEFTOVER_TAGS_RE.sub("", result)

    result = _CONSECUTIVE_BLANK_RE.sub("\n\n", result)
    return result.strip()


# --- degenerate_guards -------------------------------------------------------

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


__all__ = [
    "confidence_label",
    "sanitize_html_to_markdown",
    "_HEADING_RE",
    "_BOLD_RE",
    "_ITALIC_RE",
    "_BR_RE",
    "_UL_BLOCK_RE",
    "_OL_BLOCK_RE",
    "_LI_RE",
    "_P_RE",
    "_DIV_RE",
    "_LEFTOVER_TAGS_RE",
    "_HEADING_LEVEL_MAP",
    "_CONSECUTIVE_BLANK_RE",
    "_convert_ul",
    "_convert_ol",
    "_convert_heading",
    "_CONFIDENCE_LABELS",
    "_DEGENERATE_REPETITION_RE",
    "_detect_degenerate_repetition",
    "_strip_degenerate_repetition",
    "_DEGENERATE_LINE_REPETITION_MIN_REPEATS",
    "_DEGENERATE_LINE_MIN_LENGTH",
    "_detect_degenerate_line_repetition",
    "_strip_degenerate_line_repetition",
    "_DEGENERATE_BLANK_RUN_RE",
    "_detect_degenerate_blank_run",
    "_strip_degenerate_blank_run",
    "_DEGENERATE_PREFIX_LENGTH",
    "_DEGENERATE_PREFIX_MIN_REPEATS",
    "_detect_degenerate_growing_repetition",
    "_strip_degenerate_growing_repetition",
    "_detect_any_degenerate_repetition",
    "_strip_any_degenerate_repetition",
]
