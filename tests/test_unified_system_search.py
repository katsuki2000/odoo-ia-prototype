"""Offline tests for the single discovery interface and unchanged backend boundaries."""

import ast
from itertools import zip_longest
import json
import logging
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UnifiedSystemSearchTests(unittest.TestCase):
    def setUp(self):
        self.graph = object()
        self.calls = []
        self.objects = {'semantic_status': 'available', 'candidates': [
            {'node_id': 'model:x_case', 'model': 'x_case', 'score': 94},
            {'node_id': 'field:x_case.state', 'model': 'x_case', 'score': 71}]}
        self.sources = {'candidates': [
            {'filepath': 'case.py', 'line_start': 2, 'line_end': 5, 'sha256': 'fixture'},
            {'filepath': 'view.xml', 'line_start': 1, 'line_end': 3, 'sha256': 'fixture2'}],
            'coverage': {'files_indexed': 2, 'parse_errors': 1}, 'complete_scan': False}
        def find(graph, query, **kwargs):
            self.calls.append(('objects', graph, query, kwargs))
            return self.objects
        def search(graph, roots, query, **kwargs):
            self.calls.append(('source', graph, query, kwargs))
            return self.sources
        tree = ast.parse((ROOT / 'code_intelligence/agent/source_tools.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'search_system']
        for node in tree.body:
            node.decorator_list = []
        self.namespace = {'json': json, 'zip_longest': zip_longest, 'logger': logging.getLogger(__name__),
                          '_require_graph': lambda: self.graph, 'find_instance_candidates': find,
                          'search_source_fragments': search, '_allowed_source_roots': lambda: [],
                          '_search_limits': lambda: object()}
        exec(compile(tree, 'source_tools.py', 'exec'), self.namespace)
        self.search = self.namespace['search_system']

    def result(self, **kwargs):
        return json.loads(self.search('approval', **kwargs))

    def test_one_call_uses_both_existing_backends(self):
        result = self.result()
        self.assertEqual([item[0] for item in self.calls], ['objects', 'source'])
        self.assertTrue(all(item[1] is self.graph for item in self.calls))
        self.assertTrue(result['discovery_only'])

    def test_candidates_are_typed_and_alternated_without_score_comparison(self):
        result = self.result()
        self.assertEqual([item['kind'] for item in result['candidates']],
                         ['instance_object', 'source_fragment', 'instance_object', 'source_fragment'])
        self.assertEqual(result['candidates'][0]['score'], 94)
        self.assertNotIn('score', result['candidates'][1])

    def test_source_ranges_fingerprint_and_coverage_are_preserved(self):
        result = self.result()
        self.assertEqual(result['candidates'][1]['sha256'], 'fixture')
        self.assertEqual(result['candidates'][1]['line_end'], 5)
        self.assertEqual(result['source_coverage'], self.sources['coverage'])
        self.assertFalse(result['source_scan_complete'])

    def test_model_scope_and_limit_are_forwarded_to_both_backends(self):
        self.result(model='x_custom.case', limit=3)
        self.assertTrue(all(item[3]['model'] == 'x_custom.case' for item in self.calls))
        self.assertTrue(all(item[3]['limit'] == 3 for item in self.calls))

    def test_limit_applies_to_combined_results(self):
        result = self.result(limit=2)
        self.assertEqual(len(result['candidates']), 2)
        self.assertTrue(result['results_clipped'])
        self.assertEqual({item['kind'] for item in result['candidates']}, {'instance_object', 'source_fragment'})

    def test_large_results_are_bounded_valid_json(self):
        self.objects['candidates'] = [{'node_id': str(index), 'label': 'a' * 1800} for index in range(20)]
        raw = self.search('approval', limit=20)
        result = json.loads(raw)
        self.assertLessEqual(len(raw), 5500)
        self.assertTrue(result['results_clipped'])
        self.assertEqual(result['source_coverage'], self.sources['coverage'])

    def test_empty_query_does_not_run_either_backend(self):
        result = json.loads(self.search('  '))
        self.assertFalse(self.calls)
        self.assertFalse(result['candidates'])
        self.assertEqual(set(result['backends'].values()), {'not_run'})

    def test_missing_object_results_do_not_hide_source_results(self):
        self.objects['candidates'] = []
        result = self.result()
        self.assertEqual(len(result['candidates']), 2)
        self.assertTrue(all(item['kind'] == 'source_fragment' for item in result['candidates']))

    def test_object_failure_preserves_sources_without_exception_details(self):
        def fail(*args, **kwargs):
            raise RuntimeError('sensitive fixture details')
        self.namespace['find_instance_candidates'] = fail
        result = self.result()
        self.assertEqual(result['backends'], {'objects': 'error', 'source': 'available'})
        self.assertTrue(result['candidates'])
        self.assertNotIn('sensitive fixture details', json.dumps(result))

    def test_source_failure_preserves_objects(self):
        def fail(*args, **kwargs):
            raise RuntimeError('fixture')
        self.namespace['search_source_fragments'] = fail
        result = self.result()
        self.assertEqual(result['backends'], {'objects': 'available', 'source': 'error'})
        self.assertTrue(all(item['kind'] == 'instance_object' for item in result['candidates']))
        self.assertIsNone(result['source_scan_complete'])

    def test_semantic_unavailability_is_still_visible(self):
        self.objects['semantic_status'] = 'unavailable'
        self.assertEqual(self.result()['semantic_status'], 'unavailable')

    def test_both_failures_do_not_claim_a_complete_scan(self):
        def fail(*args, **kwargs):
            raise ValueError('fixture')
        self.namespace['find_instance_candidates'] = fail
        self.namespace['search_source_fragments'] = fail
        result = self.result()
        self.assertFalse(result['candidates'])
        self.assertEqual(set(result['backends'].values()), {'error'})
        self.assertIsNone(result['source_scan_complete'])
        self.assertIn('not proof of absence', result['notice'])

    def test_only_unified_discovery_is_registered(self):
        tree = ast.parse((ROOT / 'code_intelligence/agent/loop.py').read_text())
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'tools' for target in node.targets)
                       and isinstance(node.value, ast.List)]
        names = {node.id for assignment in assignments for node in ast.walk(assignment.value) if isinstance(node, ast.Name)}
        self.assertIn('search_system', names)
        self.assertNotIn('search_instance_objects', names)
        self.assertNotIn('search_installed_source', names)
        self.assertIn('read_source_fragment', names)

    def test_real_source_backend_works_with_unified_interface(self):
        import test_system_source_search as sources
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'custom.py'
            path.write_text('def authorize():\n    return "approval"\n')
            self.graph = type('Graph', (), {'nodes': sources.Nodes({'method': {
                'node_type': 'Method', 'model': 'x_custom.case', 'filepath': str(path)}})})()
            self.namespace['search_source_fragments'] = sources.source.search_source_fragments
            self.namespace['_allowed_source_roots'] = lambda: [root]
            self.namespace['_search_limits'] = sources.source.SearchLimits
            result = self.result(model='x_custom.case')
            fragment = next(item for item in result['candidates'] if item['kind'] == 'source_fragment')
            self.assertEqual(fragment['symbol'], 'authorize')
            self.assertEqual((fragment['line_start'], fragment['line_end']), (1, 2))
            self.assertEqual(result['backends']['source'], 'available')


if __name__ == '__main__':
    unittest.main()
