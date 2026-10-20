"""Real source inventory/MRO tests without a live Odoo environment."""

import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path, **values):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.__dict__.update(values)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixtures = importlib.import_module(
    (__package__ + '.' if __package__ else '') + 'test_runtime_metadata_graph')
source = load('_coverage_source_search', ROOT / 'code_intelligence/agent/source_search.py')


class Nodes(dict):
    def __call__(self, data=False):
        return self.items() if data else self.keys()


class Graph:
    def __init__(self, snapshot):
        self.graph = snapshot['graph']
        self.nodes = Nodes({row['id']: row for row in snapshot['nodes']})
        self.edges = snapshot['edges']
    def __contains__(self, key):
        return key in self.nodes
    def out_edges(self, key, data=False):
        return [(row['source'], row['target'], row) if data else (row['source'], row['target'])
                for row in self.edges if row['source'] == key]


class RuntimeSourceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.basePath = self.file('base/models/base_case.py',
            "class BaseCase:\n    _module = 'base'\n    _abstract = False\n    _fields = {}\n    def approve(self):\n        return 'baseguard'\n")
        self.customPath = self.file('custom/models/custom_case.py',
            "class CustomCase(BaseCase):\n    _module = 'custom'\n    def approve(self):\n        return super().approve()\n")
        base = load('_coverage_base_case', self.basePath)
        custom = load('_coverage_custom_case', self.customPath, BaseCase=base.BaseCase)
        self.env = fixtures.FakeEnvironment()
        self.env.registry = types.SimpleNamespace(models={'x.case': custom.CustomCase})
        self.paths = {'custom': str(self.root / 'custom'), 'base': str(self.root / 'base')}
        self.helper = self.file('custom/tools/limits.py', "def approval_limit():\n    return 'helperceiling'\n")
        self.xml = self.file('custom/views/case.xml', '<odoo><record id="custom_case_view" model="ir.ui.view"><field name="arch" type="xml"><form><button name="approve" string="xmlceiling"/></form></field></record></odoo>')
        self.file('base/tools/common.py', "def common_limit():\n    return 'inheritedhelper'\n")

    def file(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def snapshot(self, **kwargs):
        return fixtures.exporter.export_runtime_graph(self.env, ['custom'], 'coverage-instance', self.paths, **kwargs)

    def graph(self, **kwargs):
        return Graph(self.snapshot(**kwargs))

    def search(self, query, graph=None, **kwargs):
        return source.search_source_fragments(graph or self.graph(), [self.root], query, **kwargs)

    def test_actual_method_definition_order_follows_loaded_mro(self):
        method = self.graph().nodes['method:x.case.approve']
        self.assertEqual([site['module'] for site in method['override_sites']], ['custom', 'base'])
        self.assertEqual([site['class_name'] for site in method['override_sites']], ['CustomCase', 'BaseCase'])
        self.assertEqual([site['filepath'] for site in method['override_sites']], [str(self.customPath), str(self.basePath)])
        self.assertTrue(method['runtime_mro_order'])
        self.assertTrue(method['source_locations_complete'])
        self.assertTrue(all('end_lineno' not in site for site in method['override_sites']))

    def test_export_does_not_extract_method_bodies_or_hash_source_files(self):
        with patch.object(fixtures.exporter.inspect, 'getsourcelines', side_effect=AssertionError('No body extraction')):
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('No source reads')):
                graph = self.graph()
        self.assertIn('method:x.case.approve', graph)

    def test_selected_module_helper_is_discoverable_with_model_context(self):
        result = self.search('helperceiling', model='x.case')
        helper = next(row for row in result['candidates'] if row['filepath'] == str(self.helper))
        self.assertEqual(helper['models'], [])
        self.assertEqual(helper['context_models'], ['x.case'])
        self.assertEqual(helper['modules'], ['custom'])
        self.assertEqual(helper['sha256'], hashlib.sha256(self.helper.read_bytes()).hexdigest())

    def test_inherited_module_helper_is_in_inventory(self):
        result = self.search('inheritedhelper', model='x.case', module='base')
        self.assertTrue(result['candidates'])
        self.assertEqual(self.graph().graph['source_inventory_modules'], ['base', 'custom'])

    def test_xml_not_referenced_by_class_is_discoverable(self):
        result = self.search('xmlceiling', model='x.case')
        row = next(row for row in result['candidates'] if row['filepath'] == str(self.xml))
        self.assertEqual(row['line_start'], 1)
        self.assertEqual(row['line_end'], 1)
        self.assertEqual(row['sha256'], hashlib.sha256(self.xml.read_bytes()).hexdigest())

    def test_unrelated_and_uninstalled_modules_are_not_crawled(self):
        self.file('unrelated/helpers.py', "def leak():\n    return 'outofscope'\n")
        self.paths['unrelated'] = str(self.root / 'unrelated')
        self.env.tables['ir.module.module'].records.append({'id': 99, 'name': 'unrelated', 'state': 'installed'})
        self.assertFalse(self.search('outofscope')['candidates'])
        self.assertNotIn('unrelated', self.graph().graph['source_inventory_modules'])

    def test_wrong_model_context_is_excluded(self):
        self.assertFalse(self.search('helperceiling', model='x.other')['candidates'])
        self.assertFalse(self.search('helperceiling', module='base')['candidates'])

    def test_file_and_directory_entry_limits_refuse_partial_exports(self):
        for limits in [{'maxSourceFiles': 1}, {'maxSourceEntries': 1}]:
            with self.assertRaises(ValueError):
                self.snapshot(**limits)

    def test_external_file_and_directory_symlinks_are_not_followed(self):
        outside = self.file('outside/secret.py', "def secret():\n    return 'outsideinventory'\n")
        (self.root / 'custom/link.py').symlink_to(outside)
        (self.root / 'custom/directory_link').symlink_to(outside.parent, target_is_directory=True)
        graph = self.graph()
        self.assertEqual(graph.graph['coverage_gaps']['skipped_source_links'], 2)
        result = self.search('outsideinventory', graph)
        self.assertFalse(result['candidates'])
        self.assertFalse(result['complete_scan'])

    def test_missing_module_path_remains_an_explicit_inventory_gap(self):
        self.paths.pop('base')
        graph = self.graph()
        self.assertEqual(graph.graph['coverage_gaps']['unavailable_module_paths'], 1)
        self.assertFalse(self.search('helperceiling', graph)['complete_scan'])

    def test_explicit_method_inspector_returns_ordered_sites(self):
        result = fixtures.runtime.runtime_model_facts(self.graph(), 'x.case', 'approve')
        method = next(row for row in result['facts'] if row['node_type'] == 'Method')
        self.assertEqual([site['module'] for site in method['override_sites']], ['custom', 'base'])
        self.assertTrue(method['runtime_mro_order'])
        self.assertEqual(result['requested_method'], 'approve')
        self.assertFalse(result['truncated'])
        self.assertIn('error', fixtures.runtime.runtime_model_facts(self.graph(), 'x.case', 'missing'))

    def test_missing_method_source_preserves_slot_and_reports_gap(self):
        with patch.object(fixtures.exporter.inspect, 'getsourcefile', return_value=None):
            graph = self.graph()
        sites = graph.nodes['method:x.case.approve']['override_sites']
        self.assertEqual([site['module'] for site in sites], ['custom', 'base'])
        self.assertFalse(any(site['source_available'] for site in sites))
        self.assertFalse(graph.nodes['method:x.case.approve']['source_locations_complete'])
        self.assertGreater(graph.graph['coverage_gaps']['unavailable_method_sources'], 0)

    def test_method_locations_are_cached_for_shared_model_classes(self):
        self.env.registry.models['x.second'] = self.env.registry.models['x.case']
        with patch.object(fixtures.exporter.inspect, 'getsourcefile', wraps=fixtures.exporter.inspect.getsourcefile) as lookup:
            self.snapshot()
        functionLookups = [call for call in lookup.call_args_list if fixtures.exporter.inspect.isfunction(call.args[0])]
        self.assertEqual(len(functionLookups), 2)

    def test_small_search_budget_is_reported_not_complete_coverage(self):
        result = self.search('helperceiling', limits=source.SearchLimits(maxFiles=1))
        self.assertFalse(result['complete_scan'])
        self.assertTrue(result['coverage']['budget_exhausted'])
        self.assertFalse(result['candidates'])

    def test_direct_model_files_precede_helper_context_in_search_budget(self):
        result = self.search('approve', limits=source.SearchLimits(maxFiles=2))
        self.assertTrue(result['coverage']['budget_exhausted'])
        self.assertTrue(result['candidates'])
        self.assertTrue(all(row['filepath'] in {str(self.basePath), str(self.customPath)} for row in result['candidates']))


if __name__ == '__main__':
    unittest.main()
