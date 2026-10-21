"""Offline boundary regressions executing production functions with explicit substitutes."""

import ast
from dataclasses import dataclass
from enum import Enum
from itertools import zip_longest
import heapq
import json
import logging
from pathlib import Path
from threading import RLock
import time
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import unicodedata
from typing import Optional, List, Set, Tuple

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


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.graph = Graph()
        self.semantic = ModuleType('code_intelligence.agent.semantic_retrieval')
        self.semantic.retrieve_semantic_model_candidates_scored = Mock(
            return_value=([('business_target', 0.61)], NS(value='available')))
        self.ns = load('code_intelligence/agent/instance_search.py', {'find_instance_candidates', '_comparable'}, {
            'heapq': heapq, 'zip_longest': zip_longest,
            'strip_accents': lambda text: ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)),
            'utils': NS(default_process=lambda text: text.lower()),
            'fuzz': NS(WRatio=lambda left, right: 90 if right.startswith('x') else 0),
            'node_labels': lambda data: []})

    def find(self, **kwargs):
        with patch.dict('sys.modules', {self.semantic.__name__: self.semantic}):
            return self.ns['find_instance_candidates'](self.graph, 'approval', **kwargs)

    def test_semantic_is_not_appended_after_a_full_lexical_page(self):
        result = self.find(limit=8)
        self.assertEqual(result['candidates'][0]['node_id'], 'model:business_target')
        self.assertEqual(result['candidates'][1]['retrieval'], 'lexical')
        self.assertEqual(result['candidates'][0]['score'], 0.61)
        self.assertEqual(result['candidates'][1]['score'], 90)

    def test_semantic_survives_unified_limit_with_and_without_fragments(self):
        objects = self.find(limit=8)
        for sources in ([], [{'filepath': f'{i}.py'} for i in range(8)]):
            ns = load('code_intelligence/agent/source_tools.py', {'search_system'}, {
                'json': json, 'zip_longest': zip_longest, '_require_graph': lambda: self.graph,
                'find_instance_candidates': lambda *a, **k: objects,
                'search_source_fragments': lambda *a, **k: {'candidates': sources},
                '_allowed_source_roots': lambda: [], '_search_limits': lambda: None})
            result = json.loads(ns['search_system']('approval', limit=8))
            self.assertTrue(any(item.get('retrieval') == 'semantic' for item in result['candidates']))
            self.assertLessEqual(len(result['candidates']), 8)

    def test_duplicates_are_emitted_once(self):
        self.semantic.retrieve_semantic_model_candidates_scored.return_value = ([('x1', .7), ('x1', .6)], NS(value='available'))
        ids = [item['node_id'] for item in self.find()['candidates']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_semantic_failure_preserves_lexical_results(self):
        self.semantic.retrieve_semantic_model_candidates_scored.side_effect = TimeoutError
        result = self.find()
        self.assertEqual(result['semantic_status'], 'unavailable')
        self.assertTrue(result['candidates'])

    def test_exact_model_scope_skips_semantic(self):
        result = self.find(model='x1')
        self.semantic.retrieve_semantic_model_candidates_scored.assert_not_called()
        self.assertEqual([item['model'] for item in result['candidates']], ['x1'])

    def test_accents_still_share_the_same_comparison_form(self):
        self.assertEqual(self.ns['_comparable']('Matériel'), self.ns['_comparable']('materiel'))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.select = Mock(return_value=NS(source='systeme', confidence=.9))
        self.ns = load('core/routing/routing.py', {'route', 'route_decision'}, {
            'time': time, 'SOURCE_SELECTION_MIN_CONFIDENCE': .75, 'SOURCE_CLARIFICATION': 'source_clarification',
            'QueryRoute': Enum('Routes', {'DOCUMENTAIRE': 'documentaire', 'CODE_INTELLIGENCE': 'code_intelligence'}),
            'select_source': self.select, 'AssistantResponse': NS})

    def test_explicit_sources_bypass_selection(self):
        self.assertEqual(self.ns['route']({'source_mode': 'systeme'})['route'], 'code_intelligence')
        self.assertEqual(self.ns['route']({'source_mode': 'documentation'})['route'], 'documentaire')
        self.select.assert_not_called()

    def test_confident_automatic_system_selection(self):
        self.assertEqual(self.ns['route']({'question': 'approve'})['route'], 'code_intelligence')

    def test_confident_automatic_document_selection(self):
        self.select.return_value = NS(source='documentation', confidence=.9)
        self.assertEqual(self.ns['route']({'question': 'policy'})['route'], 'documentaire')

    def test_low_confidence_asks_for_source_without_evidence(self):
        self.select.return_value = NS(source='systeme', confidence=.74)
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
        self.invoke = Mock(return_value=({'source': 'systeme', 'confidence': .9}, 0))
        self.ns = load('core/routing/source_selection.py', {'SourceSelection', 'select_source'}, {
            'BaseModel': BaseModel, 'ConfigDict': ConfigDict, 'Field': Field, 'Literal': Literal,
            'get_chat_llm': lambda **kwargs: NS(with_structured_output=lambda *a, **k: object()),
            'invoke_with_rate_limit': self.invoke, 'with_no_think': lambda value: value,
            'HumanMessage': NS, 'SystemMessage': NS})
        self.ns['SourceSelection'].model_rebuild(_types_namespace={'Literal': Literal})

    def test_valid_structured_selection(self):
        self.assertEqual(self.ns['select_source']('approval').source, 'systeme')

    def test_malformed_selection_is_uncertain(self):
        for result in ({'source': 'other', 'confidence': .9}, {'source': 'systeme', 'confidence': 1.1}, {},
                       {'source': 'systeme', 'confidence': float('nan')}):
            self.invoke.return_value = result, 0
            self.assertEqual(self.ns['select_source']('approval').source, 'uncertain')

    def test_unavailable_provider_is_uncertain(self):
        self.invoke.side_effect = TimeoutError
        self.assertEqual(self.ns['select_source']('approval').confidence, 0)

    def test_empty_question_does_not_call_provider(self):
        self.assertEqual(self.ns['select_source'](' ').source, 'uncertain')
        self.invoke.assert_not_called()


class DisclosureTests(unittest.TestCase):
    def setUp(self):
        self.settings = ModuleType('config.settings')
        self.settings.SENSITIVE_EVIDENCE_GROUP_XMLIDS = frozenset()
        resolver = ModuleType('code_intelligence.rules.group_resolver')
        resolver._expand_implied_user_groups = lambda graph, group, result: result.update(
            {'custom.reviewer'} if group == 'custom.supervisor' else set())
        utils = ModuleType('code_intelligence.utils')
        utils.SENSITIVE_BYPASS_MARKER = '[SENSITIVE]'
        self.modules = {'config.settings': self.settings, resolver.__name__: resolver, utils.__name__: utils}
        self.ns = load('code_intelligence/rules/security_locks.py', {
            'OmittedItem', '_expand_user_groups_ordered', '_find_elevating_group', '_has_elevated_access',
            '_redact_sensitive_bypass_lines', 'gate_observation', 'filter_disclosed_evidence'},
            {'dataclass': dataclass, '_OMITTED_MARKER': 'ELEMENT OMITTED FOR AUTHORIZATION REASON'})

    def gate(self, groups):
        with patch.dict('sys.modules', self.modules):
            return self.ns['gate_observation']('locks', 'custom.case',
                'condition remains\n[SENSITIVE] hardcoded-secret@example.test', object(), groups)

    def test_default_policy_denies_even_a_group_named_in_the_source(self):
        text, omitted = self.gate(['custom.reviewer'])
        self.assertNotIn('hardcoded-secret', text)
        self.assertTrue(omitted)
        self.assertNotIn('hardcoded-secret', repr(omitted))
        self.assertIn('condition remains', text)

    def test_configured_group_can_disclose(self):
        self.settings.SENSITIVE_EVIDENCE_GROUP_XMLIDS = frozenset({'custom.reviewer'})
        text, omitted = self.gate(['custom.reviewer'])
        self.assertIn('hardcoded-secret', text)
        self.assertEqual(omitted, [])

    def test_unrelated_or_unknown_groups_do_not_authorize(self):
        self.settings.SENSITIVE_EVIDENCE_GROUP_XMLIDS = frozenset({'custom.reviewer'})
        for groups in (None, [], ['custom.writer']):
            self.assertTrue(self.gate(groups)[1])

    def test_implied_policy_group_is_supported(self):
        self.settings.SENSITIVE_EVIDENCE_GROUP_XMLIDS = frozenset({'custom.reviewer'})
        self.assertFalse(self.gate(['custom.supervisor'])[1])

    def test_dossier_cannot_bypass_text_redaction(self):
        normal, sensitive = NS(scope={}), NS(scope={'sensitive': True})
        self.assertEqual(self.ns['filter_disclosed_evidence']([normal, sensitive], False), [normal])
        self.assertEqual(self.ns['filter_disclosed_evidence']([normal, sensitive], True), [normal, sensitive])

    def test_no_source_or_acl_read_is_an_authority(self):
        tree = ast.parse((ROOT / 'code_intelligence/rules/security_locks.py').read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'_find_elevating_group', '_has_elevated_access'}]
        names = {node.id for function in functions for node in ast.walk(function) if isinstance(node, ast.Name)}
        self.assertFalse(names & {'_eval_single_permission', '_extract_has_group_xmlids_from_source', 'read_source_text'})


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.graph = object()
        self.provider = Mock(return_value=self.graph)
        graphModule = ModuleType('code_intelligence.graph')
        graphModule.get_code_intelligence_graph = self.provider
        self.modules = {graphModule.__name__: graphModule}
        self.ns = load('core/graph/verify_node.py', {'_load_graph', '_build_context'}, {
            '_evidence': lambda state: (('actual evidence',), ()),
            'answered_by_documents': lambda state: state.get('route') == 'documentaire',
            'default_base_model_methods': lambda: set(), 'VerificationContext': NS})

    def test_same_request_graph_is_reused_by_identity(self):
        context = self.ns['_build_context']({'knowledge_graph': self.graph})
        self.assertIs(context.graph, self.graph)
        self.provider.assert_not_called()

    def test_documentary_verification_does_not_load_a_code_graph(self):
        with patch.dict('sys.modules', self.modules):
            context = self.ns['_build_context']({'route': 'documentaire'})
        self.assertIsNone(context.graph)
        self.provider.assert_not_called()

    def test_fallback_uses_snapshot_aware_provider(self):
        with patch.dict('sys.modules', self.modules):
            self.assertIs(self.ns['_build_context']({'language': 'fr_FR'}).graph, self.graph)
        self.provider.assert_called_once_with(translation_languages=['fr_FR'], request_language='fr_FR')

    def test_invalid_snapshot_does_not_fall_back_to_legacy_graph(self):
        self.provider.side_effect = ValueError('invalid snapshot')
        with patch.dict('sys.modules', self.modules):
            self.assertIsNone(self.ns['_build_context']({}).graph)
        self.assertEqual(self.provider.call_count, 1)

    def test_user_question_is_not_treated_as_factual_evidence(self):
        context = self.ns['_build_context']({'question': 'invented claim', 'knowledge_graph': self.graph})
        self.assertEqual(context.texts, ('actual evidence',))


class OwnershipAndRetirementTests(unittest.TestCase):
    def test_retired_answer_rewrites_are_not_executed(self):
        tree = ast.parse((ROOT / 'code_intelligence/agent/postprocess.py').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_apply_backfill_chain')
        names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
        retired = {'_backfill_missing_required_groups', '_strip_core_only_group_mentions',
            '_backfill_missing_group_escalation_note', '_backfill_missing_security_lock_amount',
            '_backfill_missing_approval_guard_facts', '_backfill_fiscal_lock_scope_fact',
            '_correct_security_lock_threshold_contradictions'}
        self.assertFalse(names & retired)
        called = []
        def guard(name):
            def apply(answer, *args, **kwargs):
                called.append(name)
                return answer
            return apply
        namespace = {name: guard(name) for name in names if name.startswith('_') or name in {
            'backfill_missing_bounds_facts', 'backfill_missing_conditional_check_facts', 'enforce_sql_constraint_fidelity',
            'correct_button_role_contradictions', 'correct_button_visibility_contradictions'}}
        namespace.pop('_apply_backfill_chain', None)
        ns = load('code_intelligence/agent/postprocess.py', {'_apply_backfill_chain'}, namespace)
        self.assertEqual(ns['_apply_backfill_chain']('answer', 'source', 'question'), 'answer')
        self.assertEqual(len(called), 24)

    def test_retrieval_uses_its_owner_not_a_compatibility_patch(self):
        owned = Mock(return_value=('chroma', 'bm25'))
        search = Mock(return_value=[{'document': 'actual'}])
        ns = load('core/graph/graph_nodes.py', {'retrieve'}, {
            'get_retriever': owned, 'search_retrieve': search, 'USE_RERANKER': False})
        fakeGraph = ModuleType('core.graph.graph')
        fakeGraph.get_retriever = Mock(side_effect=AssertionError('compatibility target used'))
        with patch.dict('sys.modules', {fakeGraph.__name__: fakeGraph}):
            self.assertTrue(ns['retrieve']({'question': 'policy'})['retrieved_chunks'])
        owned.assert_called_once()
        fakeGraph.get_retriever.assert_not_called()

    def test_group_state_has_one_owner(self):
        client = NS(get_group_xmlids=Mock(return_value={7: 'custom.reviewer'}))
        ns = load('code_intelligence/agent/context.py', {'_resolve_user_group_xmlids'}, {
            '_GROUP_RESOLUTION_LOCK': RLock(), '_GROUP_XMLID_CACHE': {},
            '_get_admin_rpc_client': lambda: (client, 1)})
        fakeGraph = ModuleType('core.graph.graph')
        fakeGraph._GROUP_XMLID_CACHE = {7: 'wrong.instance.group'}
        with patch.dict('sys.modules', {fakeGraph.__name__: fakeGraph}):
            self.assertEqual(ns['_resolve_user_group_xmlids']([7]), ['custom.reviewer'])
            self.assertEqual(ns['_resolve_user_group_xmlids']([7]), ['custom.reviewer'])
        client.get_group_xmlids.assert_called_once()

    def test_group_resolution_failure_stays_unknown(self):
        ns = load('code_intelligence/agent/context.py', {'_resolve_user_group_xmlids'}, {
            '_GROUP_RESOLUTION_LOCK': RLock(), '_GROUP_XMLID_CACHE': {},
            '_get_admin_rpc_client': Mock(side_effect=TimeoutError)})
        self.assertEqual(ns['_resolve_user_group_xmlids']([7]), [])


class SecurityEvidenceTests(unittest.TestCase):
    def evidence(self, **overrides):
        ns = load('code_intelligence/rules/security_evidence.py', {'build_security_lock_evidence'}, {
            'make_evidence': lambda **values: NS(**values), 'EvidenceSourceType': NS(CODE='code')})
        args = dict(filepath='addons/custom_case/models/case.py', hardcoded_logins=[], exception_messages=[],
            exception_conditions=[], exception_guard_fields=[], exception_linenos=[],
            required_groups=['custom.reviewer'], required_group_methods=['approve'], required_group_linenos=[22],
            dynamic_dispatch_types=[])
        args.update(overrides)
        return ns['build_security_lock_evidence'](**args)

    def test_group_calls_are_observations_not_required_groups(self):
        for gating in (True, False):
            evidence = self.evidence(required_group_is_gating=[gating])
            group = next(item for item in evidence if ':group:' in item.source)
            self.assertIn('contains a has_group()', group.claim)
            self.assertNotIn('requires group', group.claim)
            self.assertEqual(group.scope['authorization_verdict'], 'not_evaluated')
            self.assertEqual(group.scope['lineno'], 22)

    def test_or_alternative_does_not_assert_unconditional_authorization(self):
        group = next(item for item in self.evidence(required_group_alt_conditions=['record.total < 200'])
                     if ':group:' in item.source)
        self.assertIn('record.total < 200', group.claim)
        self.assertNotIn('sufficient path', group.claim)

    def test_exception_condition_and_method_are_kept(self):
        items = self.evidence(exception_messages=['blocked'], exception_conditions=['record.total > 200'],
            exception_linenos=[25], exception_methods=['approve'])
        item = next(item for item in items if ':exception:25' in item.source)
        self.assertIn('record.total > 200', item.claim)
        self.assertIn('approve()', item.claim)

    def test_sensitive_login_evidence_is_explicitly_marked(self):
        items = self.evidence(hardcoded_logins=['private@example.test'])
        login = next(item for item in items if item.source.endswith(':hardcoded_logins'))
        self.assertTrue(login.scope['sensitive'])


if __name__ == '__main__':
    unittest.main()
