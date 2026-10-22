import hashlib

import networkx as nx
import pytest

from code_intelligence.agent.tools.source_search import SearchLimits, search_source_fragments


def _graph_for(path):
    graph = nx.DiGraph()
    graph.add_node(
        'source:demo:case.py',
        node_type='SourceFile',
        filepath=str(path),
        module='demo',
        scope_models=['x.case'],
    )
    return graph


def test_search_reads_only_graph_inventory_and_returns_fingerprint(tmp_path):
    path = tmp_path / 'case.py'
    path.write_text('def approve():\n    return "approval required"\n', encoding='utf-8')

    result = search_source_fragments(_graph_for(path), [tmp_path], 'approval')
    fragment, = result['candidates']
    assert fragment['filepath'] == str(path)
    assert fragment['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['discovery_only']
    assert 'approval required' not in str(result)


def test_search_does_not_crawl_unindexed_files(tmp_path):
    indexed = tmp_path / 'indexed.py'
    unindexed = tmp_path / 'unindexed.py'
    indexed.write_text('def approve():\n    pass\n', encoding='utf-8')
    unindexed.write_text('def leak():\n    return "secretneedle"\n', encoding='utf-8')

    result = search_source_fragments(_graph_for(indexed), [tmp_path], 'secretneedle')
    assert result['candidates'] == []


def test_model_scope_includes_explicit_context_only(tmp_path):
    path = tmp_path / 'helper.py'
    path.write_text('def approval_limit():\n    return 4\n', encoding='utf-8')
    graph = _graph_for(path)

    assert search_source_fragments(graph, [tmp_path], 'approval', model='x.case')['candidates']
    assert not search_source_fragments(graph, [tmp_path], 'approval', model='x.other')['candidates']


def test_external_path_and_symlink_are_excluded(tmp_path):
    root = tmp_path / 'addons'
    root.mkdir()
    external = tmp_path / 'outside.py'
    external.write_text('def secret():\n    return "needle"\n', encoding='utf-8')
    link = root / 'link.py'
    link.symlink_to(external)

    result = search_source_fragments(_graph_for(link), [root], 'needle')
    assert result['candidates'] == []
    assert result['coverage']['blocked_paths'] == 1
    assert not result['complete_scan']


def test_limits_are_validated_and_report_incomplete_search(tmp_path):
    path = tmp_path / 'case.py'
    path.write_text('approval\n', encoding='utf-8')
    with pytest.raises(ValueError):
        SearchLimits(max_files=0).validate()

    result = search_source_fragments(
        _graph_for(path), [tmp_path], 'approval',
        limits=SearchLimits(max_file_bytes=1),
    )
    assert result['coverage']['budget_exhausted']
    assert not result['complete_scan']


def test_candidate_models_prioritize_matching_files(tmp_path):
    first_path = tmp_path / 'a_other.py'
    second_path = tmp_path / 'z_target.py'
    first_path.write_text('def validate():\n    return False\n', encoding='utf-8')
    second_path.write_text('def validate():\n    return True\n', encoding='utf-8')

    graph = nx.DiGraph()
    graph.add_node('source:demo:a_other.py', node_type='SourceFile', filepath=str(first_path),
                   module='demo', scope_models=['other.model'])
    graph.add_node('source:demo:z_target.py', node_type='SourceFile', filepath=str(second_path),
                   module='demo', scope_models=['target.model'])

    # Without candidate models, alphabetical ordering gives a_other.py first
    default_result = search_source_fragments(graph, [tmp_path], 'validate', limit=1)
    assert default_result['candidates'][0]['filepath'] == str(first_path)

    # With candidate models, z_target.py is prioritized
    prioritized = search_source_fragments(
        graph, [tmp_path], 'validate', limit=1, candidate_models=['target.model'],
    )
    assert prioritized['candidates'][0]['filepath'] == str(second_path)


def test_token_boundary_prevents_substring_false_positives(tmp_path):
    path = tmp_path / 'case.py'
    path.write_text('description = "unrelated field"\n', encoding='utf-8')
    graph = _graph_for(path)

    result = search_source_fragments(graph, [tmp_path], 'validation des regles')
    assert result['candidates'] == []
