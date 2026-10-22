"""Unified discovery and fingerprinted source reads."""

import hashlib
import json

from langchain_core.tools import tool

from code_intelligence.agent.tools.helpers import _require_graph
from code_intelligence.agent.tools.instance_search import find_instance_candidates
from code_intelligence.agent.tools.introspection import _allowed_source_roots, read_precise_source_code
from code_intelligence.agent.tools.source_boundary import validate_source_range
from code_intelligence.agent.tools.source_search import (
    SearchLimits,
    confined_source_path,
    search_source_fragments,
)


def _search_limits():
    return SearchLimits()


@tool
def search_system(query: str, model: str = '', module: str = '', limit: int = 8) -> str:
    """Discover likely models and matching source fragments in the active graph."""
    graph = _require_graph()
    if not query.strip():
        return json.dumps({
            'candidates': [],
            'backends': {'objects': 'not_run', 'source': 'not_run'},
            'source_scan_complete': False,
            'notice': 'Empty query; no search was performed.',
            'discovery_only': True,
        }, ensure_ascii=False)
    if limit < 1:
        raise ValueError('limit must be positive.')
    limits = _search_limits()
    limit = min(limit, limits.max_fragments)
    notice = ''
    modelScope = model
    if model and not graph.has_node(f'model:{model}'):
        notice = f"'{model}' is not in the graph; model scope was ignored."
        modelScope = ''
    roots = _allowed_source_roots()
    objects = find_instance_candidates(graph, query, model=modelScope, limit=limit)
    candidateModels = [c['model'] for c in objects.get('candidates', []) if c.get('model')]
    sources = search_source_fragments(
        graph,
        roots,
        query,
        model=modelScope,
        module=module,
        limit=limit,
        limits=limits,
        candidate_models=candidateModels,
    )
    objectRows = list(objects['candidates'])
    sourceRows = list(sources['candidates'])
    candidates = []
    while objectRows or sourceRows:
        if objectRows:
            candidates.append({'kind': 'instance_object', **objectRows.pop(0)})
        if sourceRows:
            candidates.append({'kind': 'source_fragment', **sourceRows.pop(0)})
        if len(candidates) >= limit:
            break
    result = {
        'candidates': candidates,
        'backends': {
            'objects': 'available',
            'source': 'available' if roots else 'not_configured',
        },
        'semantic_status': objects['semantic_status'],
        'source_coverage': sources['coverage'],
        'source_scan_complete': sources['complete_scan'],
        'results_clipped': bool(objectRows or sourceRows),
        'discovery_only': True,
    }
    if notice:
        result['notice'] = notice
    return json.dumps(result, ensure_ascii=False)


@tool
def read_source_fragment(
    filepath: str,
    line_start: int,
    line_end: int,
    sha256: str,
) -> str:
    """Read an in-scope source range only if its fingerprint is unchanged."""
    rangeError = validate_source_range(line_start, line_end)
    if rangeError:
        return rangeError
    path = confined_source_path(filepath, _allowed_source_roots())
    if path is None:
        return 'Error: Source path is outside approved addon roots.'
    try:
        before = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return 'Error: Source file is unavailable.'
    if before != sha256:
        return 'Error: Source changed since discovery.'
    output = read_precise_source_code(
        str(path), line_start, line_end, include_citation=True,
    )
    try:
        after = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return 'Error: Source became unavailable during reading.'
    if before != after:
        return 'Error: Source changed during reading.'
    return output


__all__ = ['search_system', 'read_source_fragment']
