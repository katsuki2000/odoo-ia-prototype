"""Offline runtime export and snapshot validation; no live Odoo or credentials."""

import ast
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_runtime_graph_test'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'code_intelligence/graph')]
sys.modules[PACKAGE] = package


def load(name):
    spec = importlib.util.spec_from_file_location(PACKAGE + '.' + name, ROOT / 'code_intelligence/graph' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


exporter = load('runtime_export')
runtime = load('runtime_graph')


class BaseCase:
    _module = 'custom'
    _abstract = False
    _description = 'Custom case'
    _fields = {
        'amount': types.SimpleNamespace(type='float', string='Amount', store=True, compute=None),
        'peer_id': types.SimpleNamespace(type='many2one', string='Peer', store=True, compute=None, comodel_name='x.peer'),
    }
    def approve(self):
        return True


class PeerCase:
    _module = 'custom'
    _abstract = False
    _description = 'Peer'
    _fields = {}


class UninstalledCase:
    _module = 'not_installed'
    _abstract = False
    _fields = {}


class Rows:
    def __init__(self, records, identifiers, ids=None):
        self.records, self.identifiers, self.ids = records, identifiers, ids
    def search_read(self, domain, fields, limit):
        rows = self.records
        for key, operator, value in domain:
            if key == 'module_id.name':
                continue
            def actual(row):
                found = row.get(key)
                return found[0] if isinstance(found, tuple) else found
            if operator == '=':
                rows = [row for row in rows if actual(row) == value]
            elif operator == 'in':
                rows = [row for row in rows if actual(row) in value]
        return [dict(row) for row in rows[:limit]]
    def browse(self, ids):
        return Rows(self.records, self.identifiers, ids)
    def get_external_id(self):
        return {value: self.identifiers.get(value, '') for value in self.ids}


class FakeEnvironment:
    su = True
    context = {'lang': 'en_US'}
    cr = types.SimpleNamespace(dbname='fixture_database')
    registry = types.SimpleNamespace(models={'x.case': BaseCase, 'x.peer': PeerCase, 'x.absent': UninstalledCase})
    def __init__(self):
        self.tables = {
            'ir.module.module': Rows([{'id': 11, 'name': 'custom', 'state': 'installed', 'installed_version': '17.0.1'},
                                     {'id': 12, 'name': 'base', 'state': 'installed', 'installed_version': '17.0'}], {}),
            'ir.module.module.dependency': Rows([{'id': 13, 'module_id': (11, 'Custom'), 'name': 'base'}], {}),
            'ir.model': Rows([{'id': 21, 'model': 'x.case'}, {'id': 22, 'model': 'x.peer'}], {}),
            'res.groups': Rows([{'id': 31, 'name': 'Reviewer', 'implied_ids': [32]},
                                {'id': 32, 'name': 'Member', 'implied_ids': []}], {31: 'custom.reviewer', 32: 'base.member'}),
            'ir.model.access': Rows([{'id': 41, 'model_id': (21, 'Case'), 'name': 'Case access', 'group_id': (31, 'Reviewer'),
                                      'active': True, 'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False}], {41: 'custom.case_acl'}),
            'ir.rule': Rows([{'id': 51, 'model_id': (21, 'Case'), 'name': 'Case rule', 'groups': [31],
                             'domain_force': "[('company_id', 'in', company_ids)]", 'active': True,
                             'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': True}], {51: 'custom.case_rule'}),
            'ir.actions.act_window': Rows([{'id': 61, 'name': 'Cases', 'res_model': 'x.case'}], {61: 'custom.cases_action'}),
            'ir.ui.menu': Rows([{'id': 71, 'name': 'Cases', 'action': 'ir.actions.act_window,61', 'parent_id': False, 'groups_id': [31]}], {71: 'custom.cases_menu'}),
            'ir.ui.view': Rows([{'id': 81, 'name': 'Case form', 'model': 'x.case', 'active': True,
                                'arch_db': '<form><button name="approve" type="object" string="Approve"/></form>', 'inherit_id': False}], {81: 'custom.case_form'}),
        }
    def __getitem__(self, name):
        return self.tables[name]


class RuntimeExportTests(unittest.TestCase):
    def setUp(self):
        self.env = FakeEnvironment()
    def snapshot(self, **kwargs):
        return exporter.export_runtime_graph(self.env, ['custom'], 'fixture-instance', {'custom': str(ROOT)}, **kwargs)

    def test_only_requested_installed_model_scope_is_exported(self):
        snapshot = self.snapshot()
        models = {node['id'] for node in snapshot['nodes'] if node['node_type'] == 'Model'}
        self.assertEqual(models, {'model:x.case', 'model:x.peer'})
        self.assertEqual(snapshot['graph']['module_scope'], ['custom'])

    def test_effective_fields_and_relational_edges_are_exported(self):
        snapshot = self.snapshot()
        amount = next(node for node in snapshot['nodes'] if node['id'] == 'field:x.case.amount')
        self.assertEqual(amount['field_type'], 'float')
        self.assertEqual(amount['label'], 'Amount')
        self.assertTrue(any(edge['edge_type'] == 'RELATES_TO' and edge['target'] == 'model:x.peer' for edge in snapshot['edges']))

    def test_export_records_class_files_without_extracting_method_bodies(self):
        with patch.object(exporter.inspect, 'getsourcelines', side_effect=AssertionError('No method extraction')):
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('No source file hashing')):
                snapshot = self.snapshot()
        model = next(node for node in snapshot['nodes'] if node['id'] == 'model:x.case')
        self.assertIn(str(Path(__file__).resolve()), model['filepaths'])
        self.assertIn({'module': 'custom', 'filepath': str(Path(__file__).resolve())}, model['source_sites'])
        method = next(node for node in snapshot['nodes'] if node['id'] == 'method:x.case.approve')
        self.assertTrue(method['runtime_mro_order'])
        self.assertTrue(method['locations_only'])
        self.assertNotIn('end_lineno', method['override_sites'][0])

    def test_exported_class_sites_feed_real_ast_source_search(self):
        spec = importlib.util.spec_from_file_location('_runtime_source_search_test', ROOT / 'code_intelligence/agent/source_search.py')
        source = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = source
        spec.loader.exec_module(source)
        class Nodes(dict):
            def __call__(self, data=False):
                return self.items() if data else self.keys()
        graph = types.SimpleNamespace(nodes=Nodes({node['id']: node for node in self.snapshot()['nodes']}))
        with patch.object(source, 'python_fragments', wraps=source.python_fragments) as parse:
            result = source.search_source_fragments(graph, [ROOT], 'approve', model='x.case', module='custom')
        self.assertEqual(sum('class FakeEnvironment:' in call.args[0] for call in parse.call_args_list), 1)
        method = next(item for item in result['candidates'] if item['symbol'] == 'BaseCase.approve')
        text = Path(method['filepath']).read_text().splitlines()
        self.assertIn('def approve(self):', text[method['line_start'] - 1])
        self.assertIn('return True', text[method['line_end'] - 1])
        self.assertIn('custom', method['modules'])
        self.assertIn('x.case', method['models'])
        self.assertEqual(method['sha256'], hashlib.sha256(Path(method['filepath']).read_bytes()).hexdigest())

    def test_security_xmlids_and_edges_are_preserved(self):
        snapshot = self.snapshot()
        identifiers = {node['id'] for node in snapshot['nodes']}
        self.assertIn('acl:custom.case_acl', identifiers)
        self.assertIn('rule:custom.case_rule', identifiers)
        self.assertTrue(any(edge['edge_type'] == 'APPLIES_TO_GROUP' and edge['target'] == 'group:custom.reviewer' for edge in snapshot['edges']))

    def test_ui_buttons_are_explicitly_declarations(self):
        snapshot = self.snapshot()
        button = next(node for node in snapshot['nodes'] if node['node_type'] == 'Button')
        self.assertTrue(button['declaration_only'])
        self.assertEqual(button['view_xml_id'], 'custom.case_form')
        self.assertTrue(any(edge['edge_type'] == 'OPENS_MODEL' for edge in snapshot['edges']))

    def test_no_workflow_or_access_verdict_is_invented(self):
        snapshot = self.snapshot()
        self.assertFalse(any(edge['edge_type'] == 'TRANSITIONS_VIA' for edge in snapshot['edges']))
        self.assertNotIn('evaluate_record_rules', snapshot['graph']['available_ci_tools'])
        self.assertTrue(snapshot['graph']['limitations'])

    def test_unknown_module_is_refused(self):
        with self.assertRaises(ValueError):
            exporter.export_runtime_graph(self.env, ['not_installed'], 'fixture', {})

    def test_no_implicit_privilege_elevation(self):
        self.env.su = False
        with self.assertRaises(PermissionError):
            self.snapshot()

    def test_explicit_scope_and_identity_are_required(self):
        for modules, key in [([], 'fixture'), (['custom'], '')]:
            with self.assertRaises(ValueError):
                exporter.export_runtime_graph(self.env, modules, key, {})

    def test_model_and_row_limits_refuse_oversized_exports(self):
        for kwargs in [{'maxModels': 1}, {'maxRows': 1}]:
            with self.assertRaises(ValueError):
                self.snapshot(**kwargs)

    def test_missing_xmlid_is_a_coverage_gap_not_numeric_fallback(self):
        self.env.tables['ir.rule'].identifiers.clear()
        snapshot = self.snapshot()
        self.assertGreater(snapshot['graph']['coverage_gaps']['missing_xmlids'], 0)
        self.assertFalse(any(node['id'].startswith('rule:') for node in snapshot['nodes']))

    def test_invalid_xml_is_reported(self):
        self.env.tables['ir.ui.view'].records[0]['arch_db'] = '<form><broken></form>'
        self.assertEqual(self.snapshot()['graph']['coverage_gaps']['invalid_views'], 1)

    def test_snapshot_is_json_serializable_and_has_no_phantom_edges(self):
        snapshot = json.loads(json.dumps(self.snapshot()))
        identifiers = {node['id'] for node in snapshot['nodes']}
        self.assertTrue(all(edge['source'] in identifiers and edge['target'] in identifiers for edge in snapshot['edges']))


class SnapshotValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'snapshot.json'
        self.snapshot = exporter.export_runtime_graph(FakeEnvironment(), ['custom'], 'fixture-instance', {'custom': str(ROOT)})
    def read(self):
        self.path.write_text(json.dumps(self.snapshot))
        return runtime.read_runtime_snapshot(self.path, 'fixture-instance')

    def test_schema_identity_and_fingerprint(self):
        snapshot = self.read()
        self.assertEqual(len(snapshot['graph']['snapshot_sha256']), 64)
        self.assertEqual(snapshot['graph']['available_ci_tools'], sorted(runtime.RUNTIME_CI_TOOLS))

    def test_mismatched_instance_is_refused(self):
        self.read()
        with self.assertRaises(ValueError):
            runtime.read_runtime_snapshot(self.path, 'another-instance')

    def test_missing_expected_instance_is_refused(self):
        with self.assertRaises(ValueError):
            runtime.read_runtime_snapshot(self.path, '')

    def test_unsupported_schema_is_refused(self):
        self.snapshot['graph']['snapshot_version'] = 999
        with self.assertRaises(ValueError):
            self.read()

    def test_dangling_edge_is_refused(self):
        self.snapshot['edges'].append({'source': 'missing', 'target': 'model:x.case', 'edge_type': 'HAS_FIELD'})
        with self.assertRaises(ValueError):
            self.read()

    def test_duplicate_node_is_refused(self):
        self.snapshot['nodes'].append(copy.deepcopy(self.snapshot['nodes'][0]))
        with self.assertRaises(ValueError):
            self.read()

    def test_opt_in_wrapper_keeps_legacy_default_and_fails_without_fallback(self):
        tree = ast.parse((ROOT / 'code_intelligence/graph/__init__.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'get_code_intelligence_graph']
        namespace = {'_get_legacy_graph': lambda **kwargs: ('legacy', kwargs), '__name__': PACKAGE, '__package__': PACKAGE}
        exec(compile(tree, '__init__.py', 'exec'), namespace)
        with patch.dict('os.environ', {'CI_RUNTIME_GRAPH_PATH': ''}):
            self.assertEqual(namespace['get_code_intelligence_graph'](force_rebuild=True), ('legacy', {'force_rebuild': True}))
        with patch.dict('os.environ', {'CI_RUNTIME_GRAPH_PATH': 'missing', 'CI_RUNTIME_GRAPH_INSTANCE': ''}):
            with patch.object(runtime, 'load_runtime_graph', side_effect=ValueError('fixture')):
                with self.assertRaises(ValueError):
                    namespace['get_code_intelligence_graph']()

    @unittest.skipUnless(importlib.util.find_spec('networkx'), 'NetworkX is not installed in this sandbox')
    def test_native_networkx_graph_and_model_facts(self):
        self.read()
        graph = runtime.load_runtime_graph(self.path, 'fixture-instance')
        facts = runtime.runtime_model_facts(graph, 'x.case')
        self.assertEqual(facts['model'], 'x.case')
        self.assertTrue(any(row['node_type'] == 'AccessEntry' for row in facts['facts']))
        self.assertNotIn('TRANSITIONS_VIA', {data['edge_type'] for _, _, data in graph.edges(data=True)})
        self.assertIn('error', runtime.runtime_model_facts(graph, 'x.absent'))


if __name__ == '__main__':
    unittest.main()
