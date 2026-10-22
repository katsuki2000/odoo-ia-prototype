import hashlib
import json

import networkx as nx
import pytest

from code_intelligence.agent.tools import source
from code_intelligence.agent.tools import introspection


def _set_graph(monkeypatch, graph, roots):
    monkeypatch.setattr(source, '_require_graph', lambda: graph)
    monkeypatch.setattr(source, '_allowed_source_roots', lambda: roots)


def test_discovery_combines_object_and_source_candidates(tmp_path, monkeypatch):
    path = tmp_path / 'case.py'
    path.write_text('def approve():\n    return "approval"\n', encoding='utf-8')
    graph = nx.DiGraph()
    graph.add_node('model:x.case', node_type='Model', name='x.case', description='Approval process')
    graph.add_node(
        'source:demo:case.py', node_type='SourceFile', filepath=str(path),
        module='demo', scope_models=['x.case'],
    )
    _set_graph(monkeypatch, graph, [tmp_path])
    monkeypatch.setattr(source, 'find_instance_candidates', lambda *args, **kwargs: {
        'semantic_status': 'not_run',
        'candidates': [{'node_id': 'model:x.case', 'model': 'x.case', 'score': 90, 'labels': []}],
    })

    result = json.loads(source.search_system.invoke({'query': 'approval', 'limit': 4}))
    assert [candidate['kind'] for candidate in result['candidates']] == [
        'instance_object', 'source_fragment',
    ]
    fragment = result['candidates'][1]
    assert fragment['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['discovery_only']


def test_empty_query_does_not_call_search_backends(monkeypatch):
    graph = nx.DiGraph()
    _set_graph(monkeypatch, graph, [])
    monkeypatch.setattr(source, 'find_instance_candidates', lambda *args, **kwargs: pytest.fail())
    monkeypatch.setattr(source, 'search_source_fragments', lambda *args, **kwargs: pytest.fail())

    result = json.loads(source.search_system.invoke({'query': '   '}))
    assert not result['candidates']
    assert set(result['backends'].values()) == {'not_run'}


def test_unknown_model_scope_is_reported_and_dropped(monkeypatch):
    graph = nx.DiGraph()
    _set_graph(monkeypatch, graph, [])
    seen = []
    monkeypatch.setattr(source, 'find_instance_candidates', lambda _graph, _query, **kwargs: (
        seen.append(kwargs['model']) or {'semantic_status': 'not_run', 'candidates': []}
    ))
    monkeypatch.setattr(source, 'search_source_fragments', lambda _graph, _roots, _query, **kwargs: (
        seen.append(kwargs['model']) or {
            'candidates': [], 'coverage': {}, 'complete_scan': False,
        }
    ))

    result = json.loads(source.search_system.invoke({'query': 'approval', 'model': 'x.missing'}))
    assert seen == ['', '']
    assert "'x.missing' is not in the graph" in result['notice']


def test_source_failure_is_not_hidden(monkeypatch):
    graph = nx.DiGraph()
    _set_graph(monkeypatch, graph, [])
    monkeypatch.setattr(source, 'search_source_fragments', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()))

    with pytest.raises(RuntimeError):
        source.search_system.invoke({'query': 'approval'})


def test_source_read_checks_path_range_and_fingerprint(tmp_path, monkeypatch):
    path = tmp_path / 'case.py'
    path.write_text('def approve():\n    return True\n', encoding='utf-8')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(source, '_allowed_source_roots', lambda: [tmp_path])
    monkeypatch.setattr(introspection, '_allowed_source_roots', lambda: [tmp_path])

    answer = source.read_source_fragment.invoke({
        'filepath': str(path), 'line_start': 1, 'line_end': 2, 'sha256': digest,
    })
    assert 'def approve()' in answer
    assert 'Source:' in answer
    assert source.read_source_fragment.invoke({
        'filepath': str(path), 'line_start': 1, 'line_end': 2, 'sha256': 'stale',
    }).startswith('Error: Source changed')
    assert source.read_source_fragment.invoke({
        'filepath': str(tmp_path.parent / 'outside.py'),
        'line_start': 1, 'line_end': 2, 'sha256': digest,
    }).startswith('Error: Source path')
