"""Offline boundary regressions executing production functions with explicit substitutes."""

import ast
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)


def load(path, names, namespace=None):
    tree = ast.parse((ROOT / path).read_text())
    tree.body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    ns = {'__name__': __name__, 'logger': LOGGER, **(namespace or {})}
    exec(compile(ast.fix_missing_locations(tree), path, 'exec'), ns)
    return ns


class Nodes(dict):
    def __call__(self, data=False):
        return self.items() if data else self.keys()


class Graph:
    def __init__(self):
        self.nodes = Nodes({f'model:x{i}': {'node_type': 'Model', 'name': f'x{i}'} for i in range(8)})
        self.nodes['model:business_target'] = {'node_type': 'Model', 'name': 'business_target'}

    def __contains__(self, key):
        return key in self.nodes


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.ns = load('core/graph/verify_node.py', {'_build_context'}, {
            '_evidence': lambda state: (('actual evidence',), ()),
            'answered_by_documents': lambda state: state.get('source_mode') == 'documentation',
            'default_base_model_methods': lambda: set(), 'VerificationContext': NS})

    def test_user_question_is_not_treated_as_factual_evidence(self):
        context = self.ns['_build_context']({'question': 'invented claim'})
        self.assertEqual(context.texts, ('actual evidence',))


class OwnershipAndRetirementTests(unittest.TestCase):
    def test_retrieval_uses_its_owner_not_a_compatibility_patch(self):
        owned = Mock(return_value=('chroma', 'bm25'))
        search = Mock(return_value=[{'document': 'actual'}])
        ns = load('core/graph/graph_nodes.py', {'retrieve'}, {
            'get_retriever': owned, 'search_retrieve': search, 'RAG_TOP_K': 10})
        fake_graph = ModuleType('core.graph.graph')
        fake_graph.get_retriever = Mock(side_effect=AssertionError('compatibility target used'))
        with patch.dict('sys.modules', {fake_graph.__name__: fake_graph}):
            self.assertTrue(ns['retrieve']({'question': 'policy'})['retrieved_chunks'])
        owned.assert_called_once()
        fake_graph.get_retriever.assert_not_called()
