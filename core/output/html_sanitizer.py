"""
core/html_sanitizer.py

Backend defense against LLM-emitted raw HTML in answer text.
Converts common structural HTML tags back to Markdown equivalents
before the answer reaches the frontend or any API consumer.
"""

import re

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
