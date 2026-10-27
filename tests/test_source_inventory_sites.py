"""Source inventory compatibility tests with real bounded AST/FTS discovery."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('_class_sites_source_search', ROOT / 'code_intelligence/agent/tools/source_search.py')
source = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source
SPEC.loader.exec_module(source)


class Nodes(dict):
    def __call__(self, data=False):
        return self.items() if data else self.keys()


class SourceInventorySiteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        # search_source_fragments also walks DEFINED_IN edges (per-module inventory): no edges here.
        self.graph = types.SimpleNamespace(
            nodes=Nodes(), successors=lambda node: iter(()), get_edge_data=lambda u, v: None)
        self.path = self.addFile('atelier/case.py', 'def approve():\n    return "amberworkflow"\n')

    def addFile(self, name, content, model='', module=''):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def search(self, query='amberworkflow', **kwargs):
        return source.search_source_fragments(self.graph, [self.root], query, **kwargs)

    def test_runtime_class_sites_keep_exact_model_and_module_scope(self):
        self.graph.nodes.clear()
        self.graph.nodes['model:atelier.case'] = {
            'node_type': 'Model', 'name': 'atelier.case',
            'source_sites': [{'filepath': str(self.path), 'module': 'atelier'}]}
        result = self.search(model='atelier.case', module='atelier')
        self.assertTrue(result['candidates'])
        self.assertTrue(all(item['models'] == ['atelier.case'] and item['modules'] == ['atelier']
                            for item in result['candidates']))
        self.assertFalse(self.search(model='another.case')['candidates'])
        self.assertFalse(self.search(module='another')['candidates'])

    def test_runtime_class_sites_merge_with_legacy_override_sites(self):
        other = self.addFile('different/models/case.py', 'def legacy():\n    return "legacyneedle"\n', 'atelier.case', 'different')
        self.graph.nodes.clear()
        self.graph.nodes['model:atelier.case'] = {
            'node_type': 'Model', 'name': 'atelier.case',
            'source_sites': [{'filepath': str(self.path), 'module': 'atelier'}],
            'override_sites': [{'filepath': str(other), 'module': 'different'}]}
        self.assertTrue(self.search('legacyneedle', module='different')['candidates'])
        self.assertTrue(self.search(module='atelier')['candidates'])
        self.assertFalse(self.search('legacyneedle', module='atelier')['candidates'])


if __name__ == '__main__':
    unittest.main()
