"""Format and parser of the source reference attached to each code-graph tool call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CODE_GRAPH_DOC_TYPE = "code_graph"
CODE_GRAPH_PREFIX = "code_intelligence"
UNKNOWN_PART = "unknown"
SEPARATOR = ":"


@dataclass(frozen=True)
class CodeGraphSource:
    tool: str
    model: Optional[str]


def format_code_graph_source(tool: Optional[str], model: Optional[str]) -> str:
    return SEPARATOR.join((CODE_GRAPH_PREFIX, tool or UNKNOWN_PART, model or UNKNOWN_PART))


def parse_code_graph_source(source: str) -> Optional[CodeGraphSource]:
    parts = (source or "").split(SEPARATOR, 2)
    if len(parts) < 2 or parts[0] != CODE_GRAPH_PREFIX:
        return None
    model = parts[2] if len(parts) == 3 and parts[2] != UNKNOWN_PART else None
    return CodeGraphSource(tool=parts[1], model=model)
