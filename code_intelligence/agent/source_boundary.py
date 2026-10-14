"""Keep rendered source inside the authorized evidence boundary."""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Iterable


_CITATION = re.compile(r"\(file:///(?P<path>[^#)]+)#L(?P<start>\d+)-L(?P<end>\d+)\)")
_NUMBERED_LINE = re.compile(r"^\s*(\d+)\s*\| ?(.*)$")
_FENCE_LINE = re.compile(
    r"(?P<prefix>[ \t]*(?:(?:>|[-+*]|\d+[.)])[ \t]*)*)"
    r"(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)"
)
_OMITTED_BLOCK = "*(bloc de code omis : absent des extraits autorisés pour cette question.)*"


@dataclass(frozen=True)
class SourceExcerpt:
    path: str
    start: int
    lines: tuple[str, ...]

    @property
    def end(self) -> int:
        return self.start + len(self.lines) - 1


def validate_source_range(lineStart: int, lineEnd: int, maxLines: int = 200) -> str | None:
    """Reject invalid ranges before any filesystem access."""
    if any(type(value) is not int for value in (lineStart, lineEnd, maxLines)):
        return "Error: Source line bounds and maximum must be integers."
    if maxLines < 1 or lineStart < 1 or lineEnd < lineStart:
        return "Error: Source line range must satisfy 1 <= start <= end and maximum > 0."
    if lineEnd - lineStart + 1 > maxLines:
        return f"Error: Line range exceeds maximum safeguard limit of {maxLines} lines."
    return None


def _positive_line_number(text: str) -> int | None:
    try:
        value = int(text)
    except ValueError:
        return None
    return value if value > 0 else None


def _valid_citations(text: str) -> list[tuple[str, int, int]]:
    citations = []
    for match in _CITATION.finditer(text):
        start = _positive_line_number(match['start'])
        end = _positive_line_number(match['end'])
        if start is not None and end is not None and start <= end:
            citations.append((match['path'], start, end))
    return citations


def _source_excerpts(observations: Iterable[str]) -> list[SourceExcerpt]:
    excerpts = []
    for observation in observations:
        citations = _valid_citations(observation)
        paths = {path for path, _, _ in citations}
        if len(paths) != 1:
            continue
        path = next(iter(paths))
        ranges = [(start, end) for _, start, end in citations]
        runStart = None
        runLines = []
        for line in [*observation.splitlines(), '']:
            match = _NUMBERED_LINE.fullmatch(line)
            lineNumber = _positive_line_number(match[1]) if match else None
            isCovered = lineNumber is not None and any(start <= lineNumber <= end for start, end in ranges)
            if runLines and (not isCovered or lineNumber != runStart + len(runLines)):
                excerpts.append(SourceExcerpt(path, runStart, tuple(runLines)))
                runStart, runLines = None, []
            if isCovered:
                if runStart is None:
                    runStart = lineNumber
                runLines.append(match[2])
    return excerpts


@dataclass(frozen=True)
class _SourceBlock:
    start: int
    end: int
    fence: str
    body: str
    indent: int
    verifiable: bool


def _plain_indent(prefix: str) -> bool:
    return len(prefix) <= 3 and not prefix.strip(' ')


def _source_blocks(answer: str) -> Iterable[_SourceBlock]:
    """Find closed or truncated fences; unsupported containers fail closed."""
    lines = answer.splitlines(keepends=True)
    cursor, offset = 0, 0
    while cursor < len(lines):
        line = lines[cursor]
        opening = _FENCE_LINE.fullmatch(line.rstrip('\r\n'))
        start = offset
        cursor, offset = cursor + 1, offset + len(line)
        if opening is None:
            continue
        fence = opening['fence']
        isPlain = _plain_indent(opening['prefix'])
        bodyLines = []
        end, verifiable = len(answer), False
        while cursor < len(lines):
            line = lines[cursor]
            closing = _FENCE_LINE.fullmatch(line.rstrip('\r\n'))
            if (closing is not None and closing['fence'][0] == fence[0]
                    and len(closing['fence']) >= len(fence) and not closing['info'].strip()
                    and (not isPlain or _plain_indent(closing['prefix']))):
                end = offset + len(line.rstrip('\r\n'))
                verifiable = isPlain and _plain_indent(closing['prefix'])
                cursor, offset = cursor + 1, offset + len(line)
                break
            bodyLines.append(line)
            cursor, offset = cursor + 1, offset + len(line)
        yield _SourceBlock(start, end, fence, ''.join(bodyLines), len(opening['prefix']), verifiable)


def enforce_source_blocks(answer: str, observations: Iterable[str]) -> str:
    """Render only exact contiguous source already present in gated observations."""
    excerpts = _source_excerpts(observations)

    def replaceBlock(block: _SourceBlock) -> str:
        if not block.verifiable:
            return _OMITTED_BLOCK
        bodyLines = [
            line[min(block.indent, len(line) - len(line.lstrip(' '))):]
            for line in block.body.rstrip('\r\n').splitlines()
        ]
        sourceLines = tuple(
            numbered[2] if (numbered := _NUMBERED_LINE.fullmatch(line)) else line
            for line in bodyLines
        )
        if not sourceLines or not any(line.strip() for line in sourceLines):
            return _OMITTED_BLOCK
        window = answer[max(0, block.start - 500):block.end + 500]
        citations = _valid_citations(window)
        for excerpt in excerpts:
            for offset in range(len(excerpt.lines) - len(sourceLines) + 1):
                start = excerpt.start + offset
                end = start + len(sourceLines) - 1
                if excerpt.lines[offset:offset + len(sourceLines)] != sourceLines:
                    continue
                if any(path == excerpt.path and first <= start <= end <= last for path, first, last in citations):
                    fence = block.fence
                    return f"{fence}\n" + '\n'.join(sourceLines) + f"\n{fence}"
        return _OMITTED_BLOCK

    parts = []
    previousEnd = 0
    for block in _source_blocks(answer):
        parts.extend((answer[previousEnd:block.start], replaceBlock(block)))
        previousEnd = block.end
    parts.append(answer[previousEnd:])
    return ''.join(parts)
