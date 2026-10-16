"""Isolated offline regression tests for resolver decisions and provider configuration."""

import ast
from dataclasses import asdict, dataclass, field
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


@dataclass
class Concept:
    user_term: str
    resolved_models: list = field(default_factory=list)
    resolved_modules: list = field(default_factory=list)
    confidence: float = 1.0
    source_step: str = ''
    is_resolved: bool = True
    reason: str = ''
    diagnostics: dict = field(default_factory=dict)


class Nodes(dict):
    def __call__(self, data=False):
        return self.items() if data else self.keys()


class Edges(dict):
    def __call__(self, data=False):
        return [(a, b, value) for (a, b), value in self.items()] if data else self.keys()


class Graph:
    def __init__(self):
        self.nodes = Nodes({'model:alpha.record': {'node_type': 'Model', 'name': 'alpha.record', 'description': 'Alpha'},
                            'model:beta.record': {'node_type': 'Model', 'name': 'beta.record', 'description': 'Beta'}})
        self.edges = Edges()
    def successors(self, node):
        return [target for source, target in self.edges if source == node]
    def has_node(self, node):
        return node in self.nodes


class Provider:
    def __init__(self, endpoint='https://one.example/v1/embeddings'):
        self.endpoint = endpoint
        self.calls = []
    def name(self):
        return 'same-model-tag'
    def __call__(self, texts):
        self.calls.append(texts)
        return [[1.0, 0.5] for _text in texts]


class Store:
    def __init__(self, *args):
        pass
    def load(self):
        return {}
    def save(self, vectors):
        pass


def load_source(relativePath, namespace=None):
    name = '_audit.agent.resolution.' + Path(relativePath).stem
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / relativePath)
    module.__package__ = '_audit.agent.resolution'
    module.__dict__.update(namespace or {})
    sys.modules[name] = module
    tree = ast.parse(Path(module.__file__).read_text())
    allowed = {'typing', 'dataclasses', 'enum', 'urllib.parse', 'pathlib', 'threading', 'copy'}
    tree.body = [node for node in tree.body if not isinstance(node, ast.ImportFrom) or node.module in allowed]
    tree.body = [node for node in tree.body if not isinstance(node, ast.Import) or all(alias.name != 'chromadb' for alias in node.names)]
    import __future__
    exec(compile(tree, module.__file__, 'exec', flags=__future__.annotations.compiler_flag), module.__dict__)
    return module


class ResolverDecisionTests(unittest.TestCase):
    def setUp(self):
        self.modules = dict(sys.modules)
        self.settings = types.ModuleType('config.settings')
        self.settings.LOCAL_EMBEDDING_BASE_URL = 'https://configured.example/v1'
        self.settings.LOCAL_EMBEDDING_MODEL = 'configured-default'
        self.settings.LOCAL_EMBEDDING_API_KEY = 'fixture'
        self.settings.EMBEDDING_MODEL_NAME = 'local-default'
        self.settings.SEMANTIC_INDEX_CACHE_DIR = None
        config = types.ModuleType('config')
        config.settings = self.settings
        sys.modules['config'] = config
        sys.modules['config.settings'] = self.settings
        self.semantic = load_source('code_intelligence/agent/semantic_retrieval.py', {
            'settings': self.settings, 'SemanticIndexStore': Store,
            'node_labels': load_source('code_intelligence/agent/node_labels.py').node_labels,
            'text_key': lambda text: hashlib.sha256(text.encode()).hexdigest()})
        self.arbitration = load_source('code_intelligence/agent/resolution/arbitration.py')
        self.graph = Graph()
        self.provider = Provider()

    def tearDown(self):
        for key in set(sys.modules) - set(self.modules):
            del sys.modules[key]
        sys.modules.update(self.modules)

    def embedding_module(self):
        return load_source('document_rag/vectorstore/embedding_functions.py', {
            'EmbeddingFunction': object, 'Documents': list, 'Embeddings': list,
            'assert_local_endpoint': lambda *_args: None})

    def test_server_override_is_respected(self):
        module = self.embedding_module()
        provider = module.resolve_embedding_function('local_server', 'resolver-specific')
        self.assertEqual(provider.model, 'resolver-specific')
        self.assertEqual(provider.endpoint, self.settings.LOCAL_EMBEDDING_BASE_URL + '/embeddings')

    def test_server_default_is_preserved(self):
        provider = self.embedding_module().resolve_embedding_function('local_server')
        self.assertEqual(provider.model, 'configured-default')

    def test_light_backend_remains_disabled_provider(self):
        self.assertIsNone(self.embedding_module().resolve_embedding_function('local_light', 'unused'))

    def test_identity_separates_servers_with_same_model_tag(self):
        self.assertNotEqual(self.semantic._embedding_name(self.provider), self.semantic._embedding_name(Provider('https://two.example/v1/embeddings')))

    def test_identity_does_not_depend_on_url_credentials(self):
        first = Provider('https://one:password@one.example/v1/embeddings?token=secret')
        second = Provider('https://two:other@one.example/v1/embeddings?token=different')
        self.assertEqual(self.semantic._embedding_name(first), self.semantic._embedding_name(second))

    def test_revision_invalidates_provider_identity(self):
        first = self.semantic._embedding_name(self.provider)
        with patch.dict('os.environ', {'RESOLVER_SEMANTIC_EMBEDDING_REVISION': 'next'}):
            self.assertNotEqual(first, self.semantic._embedding_name(self.provider))

    def test_dimension_mismatch_is_an_error(self):
        with self.assertRaises(ValueError):
            self.semantic._cosine_similarity([1, 0], [1, 0, 0])

    def test_nonfinite_and_zero_vectors_are_rejected(self):
        for values in ([float('nan'), 1], [float('inf'), 1], [0, 0], []):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.semantic._validated_vector(values)

    def test_graph_label_mutation_invalidates_memory_index(self):
        self.semantic.rank_semantic_model_candidates_scored('question', self.graph, self.provider)
        self.graph.nodes['model:alpha.record']['description'] = 'Changed'
        self.semantic.rank_semantic_model_candidates_scored('question', self.graph, self.provider)
        self.assertTrue(any('Changed' in texts for texts in self.provider.calls))

    def test_identical_query_and_graph_reuse_embeddings(self):
        self.semantic.rank_semantic_model_candidates_scored('question', self.graph, self.provider)
        count = len(self.provider.calls)
        self.semantic.rank_semantic_model_candidates_scored('question', self.graph, self.provider)
        self.assertEqual(count, len(self.provider.calls))

    def arbitrate(self, raw, failFirst=False):
        class Message:
            def __init__(self, content):
                self.content = content
        messages = types.ModuleType('langchain_core.messages')
        messages.SystemMessage = messages.HumanMessage = Message
        llmModule = types.ModuleType('core.llm.llm_client')
        def invoke(client, messages):
            if failFirst:
                try:
                    client.invoke(messages)
                except TimeoutError:
                    pass
            return client.invoke(messages), 0.25
        llmModule.invoke_with_rate_limit = invoke
        llmModule.with_no_think = lambda prompt: prompt
        sys.modules['langchain_core.messages'] = messages
        sys.modules['core.llm.llm_client'] = llmModule
        class Client:
            calls = 0
            def invoke(self, messages):
                self.calls += 1
                if failFirst and self.calls == 1:
                    raise TimeoutError()
                return Message(raw)
        return self.arbitration._llm_arbitrate('Question', ['alpha.record', 'beta.record'], Client())

    def test_multiple_explicit_choices_are_supported(self):
        trace = self.arbitrate('["alpha.record", "beta.record"]')
        self.assertEqual(trace.choices, ('alpha.record', 'beta.record'))
        self.assertIsNone(trace.choice)

    def test_outside_model_rejects_entire_selection(self):
        trace = self.arbitrate('["alpha.record", "absent.model"]')
        self.assertEqual(trace.status, 'out_of_list')
        self.assertFalse(trace.choices)

    def test_empty_array_is_abstention(self):
        self.assertEqual(self.arbitrate('[]').status, 'none')

    def test_legacy_single_name_is_supported(self):
        self.assertEqual(self.arbitrate('alpha.record').choice, 'alpha.record')

    def test_retries_are_counted(self):
        trace = self.arbitrate('["alpha.record"]', failFirst=True)
        self.assertEqual(trace.attempts, 2)
        self.assertEqual(trace.waitSeconds, 0.25)

    def fuzzy_module(self, lexical, choices):
        trace = self.arbitration.ArbitrationTrace(choices[0] if len(choices) == 1 else None,
            'selected' if choices else 'none', choices=tuple(choices), attempts=1)
        return load_source('code_intelligence/agent/resolution/fuzzy_lookup.py', {
            'ResolvedConcept': Concept, '_fuzzy_match_graph': lambda *args, **kwargs: lexical,
            '_llm_arbitrate': lambda *args: trace, '_candidate_contexts': lambda *args: {},
            'HYBRID_SEMANTIC_LIMIT': 10, 'SHORTLIST_FUZZY_LIMIT': 5,
            'WIDENED_CANDIDATE_THRESHOLD': 30, 'WIDENED_CANDIDATE_LIMIT': 20})

    def test_high_score_does_not_promote_every_alternative(self):
        module = self.fuzzy_module([('alpha.record', 95), ('beta.record', 80)], ['alpha.record'])
        result = module.resolve_fuzzy_match('question', 'question', self.graph, object(), None, False)
        self.assertEqual(result.resolved_models, ['alpha.record'])

    def test_abstention_does_not_return_candidates_as_targets(self):
        module = self.fuzzy_module([('alpha.record', 95), ('beta.record', 80)], [])
        result = module.resolve_fuzzy_match('question', 'question', self.graph, object(), None, False)
        self.assertFalse(result.is_resolved)
        self.assertFalse(result.resolved_models)
        self.assertEqual(len(module.ambiguous_candidates_of(result)), 2)

    def test_multiple_selected_subjects_are_preserved(self):
        module = self.fuzzy_module([('alpha.record', 95), ('beta.record', 80)], ['alpha.record', 'beta.record'])
        result = module.resolve_fuzzy_match('question', 'question', self.graph, object(), None, False)
        self.assertEqual(result.resolved_models, ['alpha.record', 'beta.record'])

    def test_single_strict_candidate_needs_no_arbitration(self):
        module = self.fuzzy_module([('alpha.record', 95)], [])
        module._llm_arbitrate = lambda *args: self.fail('Unexpected arbitration')
        result = module.resolve_fuzzy_match('question', 'question', self.graph, None, None, False)
        self.assertEqual(result.resolved_models, ['alpha.record'])

    def test_turn_reuses_exact_decision_and_preserves_abstention(self):
        resolver = types.ModuleType('_audit.agent.resolver')
        calls = []
        def resolve(*args, **kwargs):
            calls.append(True)
            return Concept('question', is_resolved=False, diagnostics={'arbitration_attempts': '1'})
        resolver.resolve_business_term = resolve
        sys.modules['_audit.agent.resolver'] = resolver
        module = load_source('code_intelligence/agent/resolution/turn.py', {
            'ResolvedConcept': Concept, '_FUZZY_INDEX_CACHE': {}, '_TIEBREAK_RARITY_CACHE': {}})
        concept, reused = module.resolve_turn('question', self.graph, {}, llm=object())
        self.assertFalse(reused)
        result, reused = module.resolve_turn('question', self.graph, {'resolved_concept': asdict(concept)}, llm=object())
        self.assertTrue(reused)
        self.assertFalse(result.is_resolved)
        self.assertEqual(len(calls), 1)
        module.resolve_turn('new question', self.graph, {'resolved_concept': asdict(concept)}, llm=object())
        self.assertEqual(len(calls), 2)

    def test_document_manager_keeps_server_default_not_local_model(self):
        module = load_source('document_rag/vectorstore/chroma_manager.py', {
            'load_dotenv': lambda *_args: None, 'CHROMA_PATH': '.', 'DOCS_COLLECTION_NAME': 'fixture',
            'SERVER_EMBEDDING_BACKENDS': {'local_server'}, 'EmbeddingFunction': object,
            'chromadb': types.SimpleNamespace(PersistentClient=lambda **kwargs: types.SimpleNamespace(get_or_create_collection=lambda **kwargs: kwargs)),
            'resolve_embedding_function': lambda **kwargs: kwargs})
        with tempfile.TemporaryDirectory() as path, patch.dict('os.environ', {'EMBEDDING_BACKEND': 'local_server', 'EMBEDDING_MODEL': 'unrelated-local-name'}):
            manager = module.ChromaManager(db_path=path)
            self.assertEqual(manager.embedding_model, 'configured-default')

    def test_runner_uses_shared_turn_and_attempt_diagnostics(self):
        source = (ROOT / 'code_intelligence/agent/loop.py').read_text()
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertEqual(sum(node.func.id == 'resolve_turn' for node in calls), 1)
        self.assertIn("concept.diagnostics.get('arbitration_attempts'", source)


if __name__ == '__main__':
    unittest.main()
