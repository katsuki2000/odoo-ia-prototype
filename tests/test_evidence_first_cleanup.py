"""Offline boundary regressions executing production functions with explicit substitutes."""

import ast
from enum import Enum
import logging
from pathlib import Path
import time
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from pydantic import BaseModel, ConfigDict, Field

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


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.select = Mock(return_value=NS(source='system', confidence=.9))
        self.ns = load('core/routing/routing.py', {'route', 'route_decision'}, {
            'time': time, 'SOURCE_SELECTION_MIN_CONFIDENCE': .75, 'SOURCE_CLARIFICATION': 'source_clarification',
            'SOURCES': {'documentation', 'system'},
            'QueryRoute': Enum('Routes', {'DOCUMENTARY': 'documentation', 'ERP_DATA': 'system'}),
            'select_source': self.select, 'AssistantResponse': NS})

    def test_explicit_sources_bypass_selection(self):
        self.assertEqual(self.ns['route']({'source_mode': 'system'})['route'], 'system')
        self.assertEqual(self.ns['route']({'source_mode': 'documentation'})['route'], 'documentation')
        self.select.assert_not_called()

    def test_confident_automatic_system_selection(self):
        self.assertEqual(self.ns['route']({'question': 'approve'})['route'], 'system')

    def test_confident_automatic_document_selection(self):
        self.select.return_value = NS(source='documentation', confidence=.9)
        self.assertEqual(self.ns['route']({'question': 'policy'})['route'], 'documentation')

    def test_low_confidence_asks_for_source_without_evidence(self):
        self.select.return_value = NS(source='system', confidence=.74)
        result = self.ns['route']({'question': 'ambiguous'})
        self.assertEqual(result['route'], 'source_clarification')
        self.assertEqual(result['response'].sources, [])
        self.assertEqual(result['response'].confidence, 0)

    def test_uncertain_remains_uncertain_even_with_high_confidence(self):
        self.select.return_value = NS(source='uncertain', confidence=.99)
        self.assertEqual(self.ns['route']({})['route'], 'source_clarification')

    def test_invalid_ui_selection_does_not_trigger_automatic_selection(self):
        self.assertEqual(self.ns['route']({'source_mode': 'invalid'})['route'], 'source_clarification')
        self.select.assert_not_called()

    def test_missing_route_is_not_silently_documentary(self):
        self.assertEqual(self.ns['route_decision']({}), 'source_clarification')

    def test_clarification_has_a_terminal_edge(self):
        self.assertIn("'source_clarification': 'format_output'", (ROOT / 'core/graph/graph.py').read_text())


class SourceContractTests(unittest.TestCase):
    def setUp(self):
        from typing import Literal
        self.invoke = Mock(return_value={'source': 'system', 'confidence': .9})
        self.ns = load('core/routing/source_selection.py', {'SourceSelection', 'select_source'}, {
            'BaseModel': BaseModel, 'ConfigDict': ConfigDict, 'Field': Field, 'Literal': Literal,
            'get_chat_llm': lambda **kwargs: NS(with_structured_output=lambda *a, **k: object()),
            'invoke_llm': self.invoke, 'with_no_think': lambda value: value,
            'HumanMessage': NS, 'SystemMessage': NS})
        self.ns['SourceSelection'].model_rebuild(_types_namespace={'Literal': Literal})

    def test_valid_structured_selection(self):
        self.assertEqual(self.ns['select_source']('approval').source, 'system')

    def test_malformed_selection_is_uncertain(self):
        for result in ({'source': 'other', 'confidence': .9}, {'source': 'system', 'confidence': 1.1}, {},
                       {'source': 'system', 'confidence': float('nan')}):
            self.invoke.return_value = result
            self.assertEqual(self.ns['select_source']('approval').source, 'uncertain')

    def test_unavailable_provider_is_uncertain(self):
        self.invoke.side_effect = TimeoutError
        self.assertEqual(self.ns['select_source']('approval').confidence, 0)

    def test_empty_question_does_not_call_provider(self):
        self.assertEqual(self.ns['select_source'](' ').source, 'uncertain')
        self.invoke.assert_not_called()


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.ns = load('core/graph/verify_node.py', {'_build_context'}, {
            '_evidence': lambda state: (('actual evidence',), ()),
            'answered_by_documents': lambda state: state.get('route') == 'documentation',
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
