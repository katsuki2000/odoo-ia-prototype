"""Agent adapters for bounded source discovery and fingerprint-checked reading."""

import hashlib
import json
import os

from langchain_core.tools import tool

from code_intelligence.agent.source_search import SearchLimits, confined_source_path, search_source_fragments
from code_intelligence.agent.tool_helpers import _require_graph
from code_intelligence.agent.tools.introspection import _allowed_source_roots, read_precise_source_code


def _search_limits() -> SearchLimits:
    defaults = SearchLimits()
    return SearchLimits(
        maxFiles=max(1, int(os.getenv('CI_SOURCE_SEARCH_MAX_FILES', str(defaults.maxFiles)))),
        maxFileBytes=max(1, int(os.getenv('CI_SOURCE_SEARCH_MAX_FILE_BYTES', str(defaults.maxFileBytes)))),
        maxTotalBytes=max(1, int(os.getenv('CI_SOURCE_SEARCH_MAX_TOTAL_BYTES', str(defaults.maxTotalBytes)))),
        maxFragments=max(1, int(os.getenv('CI_SOURCE_SEARCH_MAX_FRAGMENTS', str(defaults.maxFragments)))),
        maxLines=200,
    )


@tool
def search_installed_source(query: str, model: str = '', module: str = '', limit: int = 8) -> str:
    """Find Python/XML source fragments by symbols or source text in the active instance graph.

    No model resolution is required. Optional exact model/module names restrict scope.
    Results contain candidate locations and fingerprints, NOT behavioral proof or source excerpts.
    Use read_source_fragment with the returned bounds and sha256 before explaining behavior.
    Coverage gaps or no matches must not be interpreted as absence of functionality.
    """
    result = search_source_fragments(_require_graph(), _allowed_source_roots(), query,
                                     model=model, module=module, limit=limit, limits=_search_limits())
    result['returned_candidates_truncated'] = False
    while len(json.dumps(result, ensure_ascii=False)) > 5500 and result['candidates']:
        result['candidates'].pop()
        result['returned_candidates_truncated'] = True
    return json.dumps(result, ensure_ascii=False)


@tool
def read_source_fragment(filepath: str, line_start: int, line_end: int, sha256: str) -> str:
    """Read a discovered source fragment, checking its fingerprint and permitted source roots.

    Pass the filepath, line bounds and sha256 returned by search_installed_source.
    If the content changed, search again rather than reading stale line locations.
    The existing confined source reader and its 200-line bound remain authoritative.
    """
    from code_intelligence.agent.source_boundary import validate_source_range
    error = validate_source_range(line_start, line_end)
    if error:
        return error
    path = confined_source_path(filepath, _allowed_source_roots())
    if path is None:
        return 'Error: Source file is not inside the approved addon roots.'
    try:
        maxBytes = _search_limits().maxFileBytes
        with path.open('rb') as handle:
            content = handle.read(maxBytes + 1)
        if len(content) > maxBytes:
            return 'Error: Source file exceeds the configured discovery size limit.'
        if hashlib.sha256(content).hexdigest() != sha256:
            return 'Error: Source changed since discovery. Search again before reading it.'
        observation = read_precise_source_code(str(path), line_start, line_end, include_citation=True)
        with path.open('rb') as handle:
            after = handle.read(maxBytes + 1)
        if len(after) > maxBytes or hashlib.sha256(after).hexdigest() != sha256:
            return 'Error: Source changed during reading. Search again before using this observation.'
        return observation
    except (OSError, UnicodeError):
        return 'Error: Discovered source file could not be read.'
