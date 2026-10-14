"""Keep rendered source inside the authorized evidence boundary."""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Iterable


_CITATION = re.compile(r"\(file:///(?P<path>[^#)]+)#L(?P<start>\d+)-L(?P<end>\d+)\)")
_NUMBERED_LINE = re.compile(r"^\s*(\d+)\s*\| ?(.*)$")
_FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,})[^\n]*\n(?P<body>.*?)^(?P=fence)[ \t]*$", re.MULTILINE | re.DOTALL)
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


def _source_excerpts(observations: Iterable[str]) -> list[SourceExcerpt]:
    excerpts = []
    for observation in observations:
        citations = list(_CITATION.finditer(observation))
        paths = {citation['path'] for citation in citations}
        if len(paths) != 1:
            continue
        path = next(iter(paths))
        ranges = [(int(citation['start']), int(citation['end'])) for citation in citations]
        runStart = None
        runLines = []
        for line in [*observation.splitlines(), '']:
            match = _NUMBERED_LINE.fullmatch(line)
            lineNumber = int(match[1]) if match else None
            isCovered = match is not None and any(start <= lineNumber <= end for start, end in ranges)
            if runLines and (not isCovered or lineNumber != runStart + len(runLines)):
                excerpts.append(SourceExcerpt(path, runStart, tuple(runLines)))
                runStart, runLines = None, []
            if isCovered:
                if runStart is None:
                    runStart = lineNumber
                runLines.append(match[2])
    return excerpts


def enforce_source_blocks(answer: str, observations: Iterable[str]) -> str:
    """Render only exact contiguous source already present in gated observations."""
    excerpts = _source_excerpts(observations)

    def replaceBlock(match: re.Match) -> str:
        bodyLines = match['body'].rstrip('\n').splitlines()
        sourceLines = tuple(
            numbered[2] if (numbered := _NUMBERED_LINE.fullmatch(line)) else line
            for line in bodyLines
        )
        if not sourceLines or not any(line.strip() for line in sourceLines):
            return _OMITTED_BLOCK
        window = answer[max(0, match.start() - 500):match.end() + 500]
        citations = [(item['path'], int(item['start']), int(item['end'])) for item in _CITATION.finditer(window)]
        for excerpt in excerpts:
            for offset in range(len(excerpt.lines) - len(sourceLines) + 1):
                start = excerpt.start + offset
                end = start + len(sourceLines) - 1
                if excerpt.lines[offset:offset + len(sourceLines)] != sourceLines:
                    continue
                if any(path == excerpt.path and first <= start <= end <= last for path, first, last in citations):
                    fence = match['fence']
                    return f"{fence}\n" + '\n'.join(sourceLines) + f"\n{fence}"
        return _OMITTED_BLOCK

    return _FENCE.sub(replaceBlock, answer)
