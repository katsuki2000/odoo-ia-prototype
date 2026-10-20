"""Offline PoC source discovery tests using real AST, XML and SQLite FTS5."""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('poc_source_search', ROOT / 'code_intelligence/agent/source_search.py')
source = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source
SPEC.loader.exec_module(source)


class Nodes(dict):
    def __call__(self, data=False):
        return self.items() if data else self.keys()


class SourceSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'addons'
        self.root.mkdir()
        self.graph = types.SimpleNamespace(nodes=Nodes())
        self.path = self.addFile('atelier/models/case.py',
            'class Case:\n    def approve(self):\n        return "amberworkflow"\n', 'atelier.case', 'atelier')

    def addFile(self, name, content, model='atelier.case', module='atelier'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        self.graph.nodes[name] = {'node_type': 'Method', 'model': model, 'module': module, 'filepath': str(path)}
        return path

    def search(self, query='amberworkflow', **kwargs):
        return source.search_source_fragments(self.graph, [self.root], query, **kwargs)

    def test_body_search_without_model_resolution(self):
        result = self.search()
        self.assertTrue(result['discovery_only'])
        self.assertTrue(any(item['symbol'] == 'Case.approve' for item in result['candidates']))
        self.assertTrue(result['complete_scan'])

    def test_candidates_do_not_return_source_body(self):
        result = self.search()
        self.assertNotIn('amberworkflow', json.dumps(result))
        self.assertTrue(all('text' not in item for item in result['candidates']))

    def test_fingerprint_matches_actual_content(self):
        result = self.search()
        self.assertEqual(result['candidates'][0]['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_changes_are_seen_without_a_cache_rebuild_command(self):
        before = self.search()['candidates'][0]['sha256']
        self.path.write_text('def proceed():\n    return "newworkflow"\n')
        self.assertFalse(self.search()['candidates'])
        after = self.search('newworkflow')['candidates'][0]
        self.assertNotEqual(after['sha256'], before)
        self.assertEqual(after['symbol'], 'proceed')

    def test_custom_module_scope(self):
        self.addFile('different/models/case.py', 'def approve():\n    return "amberworkflow"\n', 'different.case', 'different')
        result = self.search(module='atelier')
        self.assertTrue(result['candidates'])
        self.assertTrue(all('/atelier/' in item['filepath'] for item in result['candidates']))

    def test_exact_model_scope(self):
        self.addFile('different/models/case.py', 'def approve():\n    return "amberworkflow"\n', 'different.case', 'different')
        self.assertTrue(all(item['models'] == ['different.case'] for item in self.search(model='different.case')['candidates']))
        self.assertFalse(self.search(model='missing.case')['candidates'])

    def test_no_directory_crawl(self):
        unindexed = self.root / 'not_installed.py'
        unindexed.write_text('def secret():\n    return "uninstalledtoken"\n')
        self.assertFalse(self.search('uninstalledtoken')['candidates'])

    def test_external_path_is_blocked(self):
        path = Path(self.directory.name) / 'external.py'
        path.write_text('def secret():\n    return "externalneedle"\n')
        self.graph.nodes['external'] = {'node_type': 'Method', 'filepath': str(path)}
        result = self.search('externalneedle')
        self.assertFalse(result['candidates'])
        self.assertEqual(result['coverage']['blocked_paths'], 1)
        self.assertFalse(result['complete_scan'])

    def test_symlink_to_external_path_is_blocked(self):
        external = Path(self.directory.name) / 'external.py'
        external.write_text('def secret():\n    return "externalneedle"\n')
        link = self.root / 'shortcut.py'
        link.symlink_to(external)
        self.graph.nodes['link'] = {'node_type': 'Method', 'filepath': str(link)}
        self.assertEqual(self.search('externalneedle')['coverage']['blocked_paths'], 1)

    def test_no_configured_roots_is_not_a_full_scan(self):
        result = source.search_source_fragments(self.graph, [], 'amberworkflow')
        self.assertFalse(result['candidates'])
        self.assertFalse(result['complete_scan'])

    def test_files_are_deduplicated(self):
        self.graph.nodes['duplicate'] = dict(self.graph.nodes['atelier/models/case.py'])
        self.assertEqual(self.search()['coverage']['files_indexed'], 1)

    def test_parse_error_is_reported_not_absence(self):
        self.addFile('broken.py', 'def broken(:\n')
        result = self.search()
        self.assertEqual(result['coverage']['parse_errors'], 1)
        self.assertFalse(result['complete_scan'])
        self.assertTrue(result['candidates'])

    def test_oversized_file_has_explicit_coverage_gap(self):
        result = self.search(limits=source.SearchLimits(maxFileBytes=1))
        self.assertEqual(result['coverage']['oversized_files'], 1)
        self.assertFalse(result['complete_scan'])

    def test_total_byte_budget_is_bounded(self):
        result = self.search(limits=source.SearchLimits(maxTotalBytes=1))
        self.assertTrue(result['coverage']['budget_exhausted'])
        self.assertFalse(result['candidates'])

    def test_file_budget_is_bounded(self):
        self.addFile('second.py', 'def other():\n    return "amberworkflow"\n')
        result = self.search(limits=source.SearchLimits(maxFiles=1))
        self.assertEqual(result['coverage']['files_indexed'], 1)
        self.assertTrue(result['coverage']['budget_exhausted'])

    def test_fragment_budget_is_bounded(self):
        result = self.search(limits=source.SearchLimits(maxFragments=1))
        self.assertEqual(result['coverage']['fragments_indexed'], 1)
        self.assertTrue(result['coverage']['budget_exhausted'])

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            self.search(limits=source.SearchLimits(maxFiles=0))

    def test_empty_and_punctuation_queries_are_safe(self):
        for query in ('', '   ', '" ); --'):
            self.assertFalse(self.search(query)['candidates'])

    def test_query_is_not_executable_sql_or_fts_syntax(self):
        result = self.search('amberworkflow" OR missing*; DROP TABLE fragments; --')
        self.assertTrue(result['candidates'])

    def test_result_count_is_bounded(self):
        self.assertEqual(len(self.search(limit=1)['candidates']), 1)

    def test_decorator_and_async_ranges_are_actual_ast_ranges(self):
        text = '@decorator\nasync def work():\n    return 1\n'
        fragment, = source.python_fragments(text)
        self.assertEqual((fragment.symbol, fragment.start, fragment.end), ('work', 1, 3))
        self.assertEqual(fragment.text, text.rstrip())

    def test_long_fragment_range_is_not_guessed(self):
        text = 'def work():\n' + '    pass\n' * 12
        fragment, = source.python_fragments(text, maxLines=4)
        self.assertEqual((fragment.start, fragment.end), (1, 4))
        self.assertTrue(fragment.truncated)

    def test_xml_record_and_button_search(self):
        self.addFile('atelier/views/case.xml', '<odoo>\n<record id="amber_view" model="ir.ui.view">\n<field name="arch" type="xml">\n<form><button name="approve" string="Amberapproval"/></form>\n</field>\n</record>\n</odoo>\n')
        result = self.search('Amberapproval')
        self.assertTrue(any(item['filepath'].endswith('.xml') for item in result['candidates']))
        button = next(item for item in result['candidates'] if item['symbol'] == 'approve Amberapproval')
        self.assertEqual((button['line_start'], button['line_end']), (4, 4))

    def test_xml_dtd_is_refused(self):
        text = '<!DOCTYPE x [<!ENTITY data "amberworkflow">]><odoo><field name="name">&data;</field></odoo>'
        with self.assertRaises(ValueError):
            source.xml_fragments(text)

    def test_xml_malformed_input_is_reported(self):
        self.addFile('bad.xml', '<odoo><record id="broken"></odoo>')
        self.assertEqual(self.search()['coverage']['parse_errors'], 1)

    def test_override_site_paths_are_discoverable(self):
        self.graph.nodes['override'] = {'node_type': 'Method', 'model': 'atelier.case',
                                       'override_sites': [{'filepath': str(self.path), 'module': 'atelier'}]}
        self.assertTrue(self.search(module='atelier')['candidates'])


class SourceReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'case.py'
        self.path.write_text('def approve():\n    return 1\n')
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.readerCalls = []
        def reader(*args, **kwargs):
            self.readerCalls.append((args, kwargs))
            return 'Source: real fixture reader output'
        tree = ast.parse((ROOT / 'code_intelligence/agent/source_tools.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'read_source_fragment']
        for node in tree.body:
            node.decorator_list = []
        namespace = {'hashlib': hashlib, '_allowed_source_roots': lambda: [self.root],
                     'confined_source_path': source.confined_source_path,
                     '_search_limits': source.SearchLimits, 'read_precise_source_code': reader}
        exec(compile(tree, 'source_tools.py', 'exec'), namespace)
        self.read = namespace['read_source_fragment']
        boundary = types.ModuleType('code_intelligence.agent.source_boundary')
        boundary.validate_source_range = lambda start, end: None if type(start) is int and type(end) is int and 1 <= start <= end <= start + 199 else 'Error: invalid range'
        self.modules = patch.dict(sys.modules, {boundary.__name__: boundary})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_current_fingerprint_delegates_to_existing_reader(self):
        answer = self.read(str(self.path), 1, 2, self.digest)
        self.assertIn('real fixture reader output', answer)
        self.assertEqual(len(self.readerCalls), 1)
        self.assertTrue(self.readerCalls[0][1]['include_citation'])

    def test_stale_fingerprint_is_refused(self):
        self.path.write_text('def different():\n    return 2\n')
        self.assertIn('Source changed', self.read(str(self.path), 1, 2, self.digest))
        self.assertFalse(self.readerCalls)

    def test_invalid_range_is_refused_before_reading(self):
        self.assertIn('Error:', self.read(str(self.path), 0, 500, self.digest))
        self.assertFalse(self.readerCalls)

    def test_source_outside_roots_is_refused(self):
        self.assertIn('approved addon roots', self.read('/not/an/approved/source.py', 1, 2, self.digest))
        self.assertFalse(self.readerCalls)

    def test_content_change_during_read_is_refused(self):
        def changingReader(*args, **kwargs):
            self.path.write_text('changed')
            return 'Stale observation'
        self.read.__globals__['read_precise_source_code'] = changingReader
        answer = self.read(str(self.path), 1, 2, self.digest)
        self.assertIn('changed during reading', answer)
        self.assertNotIn('Stale observation', answer)


class SourceAgentBoundaryTests(unittest.TestCase):
    def setUp(self):
        import test_single_investigation_loop as boundary
        self.boundary = boundary
        self.fixture = boundary.ExecutionBoundaryTests()
        self.fixture.setUp()
        self.fixture.namespace['DISCOVERY_TOOLS'].add('search_installed_source')
        self.fixture.namespace['PER_TOOL_OBSERVATION_CAPS']['read_source_code'] = 9000

    def test_source_candidates_are_not_counted_as_evidence(self):
        ctx = self.boundary.Context({'search_installed_source': self.boundary.Tool()})
        self.fixture.call(ctx, 'search_installed_source', {'query': 'approval'})
        self.assertFalse(ctx.tool_observations)
        self.assertGreater(ctx.discovery_chars, 0)

    def test_source_fragment_uses_existing_source_gate_and_evidence_kind(self):
        gateCalls = []
        self.fixture.namespace['gate_observation'] = lambda **kwargs: (gateCalls.append(kwargs) or kwargs['observation'], [])
        ctx = self.boundary.Context({'read_source_fragment': self.boundary.Tool()})
        self.fixture.call(ctx, 'read_source_fragment', {'filepath': 'fixture.py', 'line_start': 1, 'line_end': 2, 'sha256': 'fixture'})
        self.assertEqual(gateCalls[0]['tool_name'], 'read_source_code')
        self.assertEqual(ctx.tool_observation_tools, ['read_source_code'])

    def test_stale_source_refusal_does_not_become_evidence(self):
        ctx = self.boundary.Context({'read_source_fragment': self.boundary.Tool('Error: Source changed since discovery.')})
        self.fixture.call(ctx, 'read_source_fragment')
        self.assertFalse(ctx.tool_observations)
        self.assertTrue(ctx.execution_failed)

    def test_tools_are_registered_in_single_agent(self):
        text = (ROOT / 'code_intelligence/agent/loop.py').read_text()
        self.assertIn('tools = [search_instance_objects, search_installed_source, read_source_fragment,', text)
        self.assertIn('create_react_agent', text)
        self.assertNotIn('run_predispatch_chain', text)


if __name__ == '__main__':
    unittest.main()
