"""Offline plan-to-executor tests with explicit graph, LLM and tool boundaries."""

import ast
from dataclasses import dataclass, field
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Concept:
    resolved_models: list = field(default_factory=lambda: ['atelier.dossier'])
    resolved_modules: list = field(default_factory=list)
    is_resolved: bool = True
    confidence: float = 0.8


class Nodes(dict):
    def __call__(self, data=False):
        return self.items() if data else self.keys()


class Graph:
    def __init__(self):
        self.nodes = Nodes({'model:atelier.dossier': {'node_type': 'Model', 'name': 'atelier.dossier', 'filepaths': ['fixture.py']},
            'method:atelier.dossier.liberer_dossier': {'node_type': 'Method', 'model': 'atelier.dossier',
                'name': 'liberer_dossier', 'filepath': 'fixture.py', 'lineno': 4, 'end_lineno': 12},
            'field:atelier.dossier.x_score': {'node_type': 'Field', 'model': 'atelier.dossier', 'name': 'x_score'}})
        self.links = []
    def edges(self, data=False):
        return self.links if data else [(source, target) for source, target, _edge in self.links]


@dataclass
class Context:
    G: object
    concept: object
    question: str
    tool_map: dict = field(default_factory=dict)
    intent: str = 'governance_security'
    hop_cap: int = 8
    hop_count: int = 0
    hop_index: int = 0
    llm_call_count: int = 0
    llm_wait: float = 0.0
    resolved_user_group_xmlids: list = field(default_factory=lambda: ['fixture.allowed'])
    security_principals: dict = field(default_factory=dict)
    requester_groups_known: bool = True
    seen_calls: set = field(default_factory=set)
    tool_observations: list = field(default_factory=list)
    tool_observation_models: list = field(default_factory=list)
    tool_observation_tools: list = field(default_factory=list)
    omitted_items: list = field(default_factory=list)
    per_hop_times: list = field(default_factory=list)
    matched_dispatchers: list = field(default_factory=list)
    system_prompt_suffix: str = ''
    trace_id: str = 'fixture'
    trace_logger: object = field(default_factory=lambda: types.SimpleNamespace(log_hop=lambda **kwargs: None))
    @property
    def hop_budget_exhausted(self):
        return self.hop_count >= self.hop_cap


class Tool:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
    def invoke(self, arguments):
        self.calls.append(arguments)
        if self.fail:
            raise RuntimeError('fixture failure')
        return 'Recorded evidence'


class CapabilityInvestigationTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(sys.modules)
        for name, directory in [('code_intelligence', 'code_intelligence'), ('code_intelligence.agent', 'code_intelligence/agent')]:
            module = types.ModuleType(name)
            module.__path__ = [str(ROOT / directory)]
            sys.modules[name] = module
        settings = types.ModuleType('config.settings')
        settings.CI_MAX_HOPS = 8
        settings.SEMANTIC_INDEX_CACHE_DIR = None
        sys.modules['config.settings'] = settings
        ontology = types.ModuleType('code_intelligence.rules.ontology')
        ontology.BehavioralTag = Enum('BehavioralTag', {'DUMMY': 'dummy'})
        ontology.TechnicalTag = Enum('TechnicalTag', {'DUMMY': 'dummy'})
        sys.modules[ontology.__name__] = ontology
        core = types.ModuleType('core.schemas')
        core.QueryRoute = Enum('QueryRoute', {'CODE_INTELLIGENCE': 'code_intelligence', 'DONNEES_ERP': 'donnees_erp', 'DOCUMENTAIRE': 'documentaire'})
        sys.modules[core.__name__] = core
        semantic = types.ModuleType('code_intelligence.agent.semantic_retrieval')
        def unavailable():
            raise RuntimeError('Offline embedding fixture')
        semantic.build_semantic_embedding_function = unavailable
        for name in ('_build_index', '_embedding_name', '_query_embedding', '_cosine_similarity'):
            setattr(semantic, name, None)
        store = types.ModuleType('code_intelligence.agent.semantic_index_store')
        store.SemanticIndexStore = object
        sys.modules[semantic.__name__] = semantic
        sys.modules[store.__name__] = store
        self.schemas = self.load('investigation_schemas')
        self.catalogue = self.load('capability_catalogue')
        self.planner = self.load('capability_planner')
        self.actualSelector = self.planner._select_capabilities
        self.followupPatch = patch.object(self.planner, '_select_capabilities', return_value=([], 'Sufficient evidence or no safe continuation.', 0, 0.0))
        self.followupPatch.start()
        context = types.ModuleType('code_intelligence.agent.context')
        context.DispatchContext = Context
        sys.modules[context.__name__] = context
        self.dispatch = self.load('capability_dispatch')
        self.loop = types.ModuleType('code_intelligence.agent.loop')
        tree = ast.parse((ROOT / 'code_intelligence/agent/loop.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'execute_tool_calls']
        namespace = self.loop.__dict__
        namespace.update(DispatchContext=Context, json=__import__('json'), time=__import__('time'), logger=__import__('logging').getLogger(__name__),
            _tool_call_key=lambda name, arguments: None, UnknownPrincipalError=PermissionError,
            _override_user_groups_arg=lambda name, arguments, groups, principals, **kwargs: dict(arguments, user_groups_json=str(groups)) if name == 'evaluate_record_rules' else arguments,
            _truncate_observation_for_budget=lambda ctx, observation, cap: observation,
            PER_TOOL_OBSERVATION_CAPS={}, DEFAULT_OBSERVATION_CAP=2500,
            MAX_TOTAL_OBSERVATION_CHARS=35000, DISCOVERY_TOOLS=set(),
            _record_amount_fact=lambda *args: None,
            gate_observation=lambda **kwargs: (kwargs['observation'], []),
            ToolMessage=lambda **kwargs: types.SimpleNamespace(**kwargs))
        exec(compile(tree, str(ROOT / 'code_intelligence/agent/loop.py'), 'exec'), namespace)
        sys.modules[self.loop.__name__] = self.loop
        self.graph = Graph()
        self.concept = Concept()

    def tearDown(self):
        self.followupPatch.stop()
        for name in set(sys.modules) - set(self.saved):
            del sys.modules[name]
        sys.modules.update(self.saved)

    def load(self, name):
        qualified = 'code_intelligence.agent.' + name
        spec = importlib.util.spec_from_file_location(qualified, ROOT / 'code_intelligence/agent' / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
        return module

    def candidates(self):
        return self.catalogue.build_capability_catalogue(self.graph, self.concept)

    def choose(self, action):
        return next(item for item in self.candidates() if item.action.value == action)

    def plan(self, items):
        with patch.object(self.planner, '_select_capabilities', return_value=([item.identifier for item in items], 'Evidence required.', 1, 0.2)):
            return self.planner.generate_investigation_plan('Une formulation sans mots declencheurs', self.concept, self.graph,
                intent=self.schemas.QuestionIntent.GOVERNANCE_SECURITY)

    def context(self, items, tools=None, cap=8):
        return self.dispatch.PlannedDispatchContext(G=self.graph, concept=self.concept, question='Question',
            tool_map=tools or {}, hop_cap=cap, investigation_plan=self.plan(items).to_display_dict())

    def test_custom_single_site_method_is_available(self):
        item = self.choose('analyze_method_override_chain')
        self.assertEqual(item.arguments['method_name'], 'liberer_dossier')

    def test_no_standard_method_is_invented(self):
        self.assertFalse(any(item.arguments.get('method_name') == '_create_invoices' for item in self.candidates()))

    def test_source_ranges_are_recorded_not_guessed(self):
        item = self.choose('read_source_code')
        self.assertEqual(item.arguments, {'filepath': 'fixture.py', 'line_start': 4, 'line_end': 12})
        self.graph.nodes['method:atelier.dossier.liberer_dossier'].pop('end_lineno')
        self.assertFalse(any(item.action.value == 'read_source_code' for item in self.candidates()))

    def test_custom_field_is_available(self):
        self.assertEqual(self.choose('field_change_impact').arguments['field_name'], 'x_score')

    def test_identical_description_and_translations_are_listed_once(self):
        label = {'label': 'Dossier atelier', 'language': 'en_US'}
        self.graph.nodes['model:atelier.dossier'].update(
            description='Dossier atelier', business_labels=[label, dict(label, language='fr_FR')])
        description = self.choose('describe_navigation_path').description
        self.assertEqual(description.count('Dossier atelier'), 1)

    def test_unresolved_subject_has_no_inventory(self):
        self.concept.is_resolved = False
        self.assertEqual(self.candidates(), [])

    def test_extension_only_module_is_supported(self):
        self.concept.resolved_models = []
        self.concept.resolved_modules = ['atelier_extension']
        self.graph.links = [('model:atelier.dossier', 'module:atelier_extension', {'edge_type': 'DEFINED_IN', 'role': 'extends'})]
        self.assertTrue(self.candidates())

    def test_all_resolved_models_receive_capabilities(self):
        self.graph.nodes['model:x_audit.sheet'] = {'node_type': 'Model', 'name': 'x_audit.sheet'}
        self.concept.resolved_models.append('x_audit.sheet')
        self.assertEqual({item.target for item in self.candidates()}, {'atelier.dossier', 'x_audit.sheet'})

    def test_plan_preserves_arguments_in_display_roundtrip(self):
        item = self.choose('analyze_method_override_chain')
        step = self.plan([item]).to_display_dict()['steps'][0]
        self.assertEqual(step['arguments'], item.arguments)
        self.assertEqual(step['capability_id'], item.identifier)

    def test_arbitrary_wording_does_not_gate_selected_custom_method(self):
        item = self.choose('analyze_method_override_chain')
        tool = Tool()
        ctx = self.context([item], {item.action.value: tool})
        ctx.question = 'Qui a le dernier mot sur ce dossier ?'
        self.dispatch.run_planned_investigation(ctx)
        self.assertEqual(tool.calls, [item.arguments])
        self.assertEqual(ctx.hop_count, 1)

    def test_parameter_injection_rejects_plan_before_execution(self):
        item = self.choose('analyze_method_override_chain')
        tool = Tool()
        ctx = self.context([item], {item.action.value: tool})
        ctx.investigation_plan['steps'][0]['arguments']['user_groups_json'] = '["forged.admin"]'
        self.dispatch.run_planned_investigation(ctx)
        self.assertFalse(tool.calls)
        self.assertIn('no longer matches', ctx.system_prompt_suffix)

    def test_changed_graph_invalidates_whole_plan(self):
        item = self.choose('analyze_method_override_chain')
        tool = Tool()
        ctx = self.context([item], {item.action.value: tool})
        del self.graph.nodes['method:atelier.dossier.liberer_dossier']
        self.dispatch.run_planned_investigation(ctx)
        self.assertFalse(tool.calls)

    def test_failed_tool_consumes_budget(self):
        first = self.choose('describe_workflow')
        second = self.choose('analyze_method_override_chain')
        failing, other = Tool(fail=True), Tool()
        ctx = self.context([first, second], {first.action.value: failing, second.action.value: other}, cap=1)
        self.dispatch.run_planned_investigation(ctx)
        self.assertEqual(ctx.hop_count, 1)
        self.assertFalse(other.calls)
        self.assertIn('not executed', ctx.system_prompt_suffix)

    def test_duplicate_failed_call_is_not_reexecuted(self):
        item = self.choose('describe_workflow')
        tool = Tool(fail=True)
        ctx = self.context([item], {item.action.value: tool})
        self.dispatch.run_planned_investigation(ctx)
        self.dispatch.run_planned_investigation(ctx)
        self.assertEqual(len(tool.calls), 1)

    def test_abstention_does_not_trigger_legacy_keyword_dispatch(self):
        ctx = self.context([])
        ctx.question = 'approval amount invoice workflow access'
        self.dispatch.run_planned_investigation(ctx)
        self.assertEqual(ctx.hop_count, 0)
        self.assertIn('No safe capability', ctx.system_prompt_suffix)

    def test_selected_source_is_associated_with_its_model(self):
        item = self.choose('read_source_code')
        ctx = self.context([item], {'read_source_code': Tool()})
        self.dispatch.run_planned_investigation(ctx)
        self.assertEqual(ctx.tool_observation_models, ['atelier.dossier'])

    def test_permission_variants_remain_distinct(self):
        items = [item for item in self.candidates() if item.action.value == 'evaluate_record_rules']
        self.assertEqual({item.arguments['permission'] for item in items}, {'read', 'write', 'create', 'unlink'})
        self.assertEqual(len({item.identifier for item in items}), 4)

    def test_missing_tool_is_not_evidence_of_absent_behavior(self):
        ctx = self.context([self.choose('describe_workflow')])
        self.dispatch.run_planned_investigation(ctx)
        self.assertFalse(ctx.tool_observations)
        self.assertIn('not executed', ctx.system_prompt_suffix)

    def test_fallback_is_intent_driven_not_question_keywords(self):
        with patch.object(self.planner, '_select_capabilities', return_value=(None, 'Unavailable', 1, 0)):
            plan = self.planner.generate_investigation_plan('Aucune expression attendue ici', self.concept, self.graph,
                intent=self.schemas.QuestionIntent.WORKFLOW_STATE)
        self.assertEqual({step.action.value for step in plan.steps}, {'describe_workflow', 'analyze_server_actions'})
        self.assertEqual(plan.source.value, 'fallback_heuristic')

    def test_non_ci_intent_does_not_call_planner_llm(self):
        with patch.object(self.planner, '_select_capabilities', side_effect=AssertionError('Unexpected LLM')):
            plan = self.planner.generate_investigation_plan('Question', self.concept, self.graph,
                intent=self.schemas.QuestionIntent.ERP_DATA_QUERY)
        self.assertFalse(plan.steps)

    def test_unknown_structured_id_is_rejected(self):
        messages = types.ModuleType('langchain_core.messages')
        messages.SystemMessage = messages.HumanMessage = lambda **kwargs: kwargs
        sys.modules[messages.__name__] = messages
        llm = types.ModuleType('core.llm.llm_client')
        client = types.SimpleNamespace(invoke=lambda messages: self.planner.CapabilitySelection(capability_ids=['invented'], rationale='Bad'))
        llm.get_chat_llm = lambda **kwargs: types.SimpleNamespace(with_structured_output=lambda *args, **kwargs: client)
        llm.invoke_with_rate_limit = lambda counted, messages, **kwargs: (counted.invoke(messages), 0.1)
        llm.with_no_think = lambda prompt: prompt
        sys.modules[llm.__name__] = llm
        selected, _reason, attempts, _wait = self.actualSelector('Question', self.candidates())
        self.assertIsNone(selected)
        self.assertEqual(attempts, 1)

    def test_followup_uses_observations_without_repeating_the_first_call(self):
        first = self.choose('analyze_method_override_chain')
        second = self.choose('read_source_code')
        methodTool, sourceTool = Tool(), Tool()
        ctx = self.context([first], {first.action.value: methodTool, second.action.value: sourceTool})
        with patch.object(self.planner, '_select_capabilities', side_effect=[
            ([second.identifier], 'Read discovered implementation', 1, 0.1),
            ([], 'Enough evidence', 1, 0.1),
        ]) as selector:
            self.dispatch.run_planned_investigation(ctx)
        self.assertEqual(len(methodTool.calls), 1)
        self.assertEqual(len(sourceTool.calls), 1)
        self.assertEqual(ctx.hop_count, 2)
        self.assertTrue(selector.call_args_list[0].kwargs['observations'])
        self.assertEqual(len(ctx.investigation_plan['steps']), 2)

    def test_shortlist_is_bounded_and_keeps_multiple_models(self):
        base = self.choose('describe_workflow')
        candidates = [self.catalogue.Capability(base.action, model, {'model_name': model, 'index': index}, 'Inventory')
                      for model in ('atelier.dossier', 'x_audit.sheet') for index in range(150)]
        shortlist, truncated = self.catalogue.shortlist_capabilities('Question', candidates)
        self.assertTrue(truncated)
        self.assertEqual(len(shortlist), self.catalogue.MAX_CANDIDATES)
        self.assertEqual({item.target for item in shortlist}, {'atelier.dossier', 'x_audit.sheet'})

    def test_navigation_receives_requester_groups(self):
        item = self.choose('describe_navigation_path')
        tool = Tool()
        ctx = self.context([item], {item.action.value: tool})
        self.dispatch.run_planned_investigation(ctx)
        self.assertEqual(__import__('json').loads(tool.calls[0]['user_groups_json']), ['fixture.allowed'])

    def test_unknown_navigation_identity_is_not_an_empty_group_list(self):
        item = self.choose('describe_navigation_path')
        tool = Tool()
        ctx = self.context([item], {item.action.value: tool})
        ctx.requester_groups_known = False
        self.dispatch.run_planned_investigation(ctx)
        self.assertIsNone(__import__('json').loads(tool.calls[0]['user_groups_json']))

    def test_no_keyword_chain_is_used_by_active_predispatch(self):
        source = (ROOT / 'code_intelligence/agent/predispatch.py').read_text()
        self.assertIn('run_planned_investigation', source)
        self.assertNotIn('dispatch_security_locks', source)

    def test_active_runner_uses_native_loop_not_legacy_plans(self):
        source = (ROOT / 'code_intelligence/agent/loop.py').read_text()
        self.assertIn('create_react_agent', source)
        self.assertNotIn('run_predispatch_chain', source)
        self.assertNotIn('generate_investigation_plan', source)


if __name__ == '__main__':
    unittest.main()
