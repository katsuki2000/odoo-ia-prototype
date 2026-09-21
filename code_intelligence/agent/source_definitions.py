"""
code_intelligence/agent/source_definitions.py

Line spans of the def/class definitions declared in a Python source file,
used to check that a cited line range actually belongs to the definition
a code block claims to show (todo/contexte.txt section 873).
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DefinitionSpans = Dict[str, List[Tuple[int, int]]]

_DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@lru_cache(maxsize=32)
def _parse_spans(path: str, mtime_ns: int) -> Optional[DefinitionSpans]:
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    spans: DefinitionSpans = {}
    for node in ast.walk(tree):
        if isinstance(node, _DEFINITION_NODES):
            first_line = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            spans.setdefault(node.name, []).append((first_line, node.end_lineno))
    return spans


def definition_spans(path: Path) -> Optional[DefinitionSpans]:
    """None when the file is missing or is not parseable Python."""
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    return _parse_spans(str(path), mtime_ns)


def range_overlaps_definition(spans: DefinitionSpans, name: str, start: int, end: int) -> bool:
    return any(first <= end and start <= last for first, last in spans.get(name, ()))
