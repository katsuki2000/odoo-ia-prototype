"""Offline execution-boundary tests; native LangGraph smoke test is optional."""

import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
import importlib.util
import json
import logging
from pathlib import Path
from threading import Barrier
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
import types

from code_intelligence.agent.tools.execution import UnknownPrincipalError, _override_user_groups_arg

ROOT = Path(__file__).resolve().parents[1]


def functions(path, names, namespace=None):
    tree = ast.parse((ROOT / path).read_text())
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    namespace = namespace or {}
    exec(compile(tree, path, 'exec'), namespace)
    return namespace


@dataclass
class Context:
    tool_map: dict
    hop_cap: int = 4
    hop_count: int = 0
    hop_index: int = 0
    G: object = None
    question: str = 'Question'
    resolved_user_group_xmlids: list = field(default_factory=lambda: ['fixture.member'])
    requester_groups_known: bool = True
    security_principals: dict = field(default_factory=dict)
    fallback_reason: str = None
    final_message_preview: str = None
    seen_calls: set = field(default_factory=set)
    tool_observations: list = field(default_factory=list)
    tool_observation_models: list = field(default_factory=list)
    tool_observation_tools: list = field(default_factory=list)
    omitted_items: list = field(default_factory=list)
    per_hop_times: list = field(default_factory=list)
    trace_id: str = 'fixture'
    trace_logger: object = field(default_factory=lambda: SimpleNamespace(log_hop=lambda **kwargs: None, log_failure=lambda *args, **kwargs: None))
    concept: object = field(default_factory=lambda: SimpleNamespace(resolved_models=[], is_resolved=False))
    orm_tool_names: set = field(default_factory=lambda: {'search_read'})

    @property
    def hop_budget_exhausted(self):
        return self.hop_count >= self.hop_cap


class Tool:
    def __init__(self, result='Real fixture observation', fail=False):
        self.calls = []
        self.result = result
        self.fail = fail

    def invoke(self, arguments):
        self.calls.append(arguments)
        if self.fail:
            raise RuntimeError('sensitive fixture error')
        return self.result


class ExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.namespace = functions('code_intelligence/agent/tools/execution.py', {'execute_tool_calls'}, {
            'DispatchContext': Context, 'json': json, 'time': time, 'logger': logging.getLogger(__name__),
            'ToolMessage': lambda **kwargs: SimpleNamespace(**kwargs),
            'UnknownPrincipalError': UnknownPrincipalError, '_override_user_groups_arg': _override_user_groups_arg,
            'MAX_TOTAL_OBSERVATION_CHARS': 35000, 'PER_TOOL_OBSERVATION_CAPS': {},
            'DEFAULT_OBSERVATION_CAP': 2500, 'DISCOVERY_TOOLS': {'search_instance_objects'}, 'NOT_FOUND_MARKER': 'was not found in the indexed knowledge graph',
            '_truncate_observation_for_budget': lambda ctx, text, cap: text[:cap],
            'gate_observation': lambda **kwargs: (kwargs['observation'], []),
        })
        self.execute = self.namespace['execute_tool_calls']

    def call(self, ctx, name, arguments=None):
        messages = []
        self.execute(ctx, SimpleNamespace(tool_calls=[{'name': name, 'args': arguments or {}, 'id': 'fixture'}]), messages)
        return messages[-1].content

    def test_successful_analysis_registers_only_its_target(self):
        tool = Tool()
        ctx = Context({'describe_workflow': tool})
        self.call(ctx, 'describe_workflow', {'model_name': 'x_fixture.case'})
        self.assertEqual(ctx.concept.resolved_models, ['x_fixture.case'])
        self.assertEqual(ctx.tool_observation_tools, ['describe_workflow'])

    def test_discovery_does_not_become_behavior_evidence(self):
        ctx = Context({'search_instance_objects': Tool()})
        self.call(ctx, 'search_instance_objects', {'query': 'anything'})
        self.assertFalse(ctx.tool_observations)
        self.assertFalse(ctx.concept.resolved_models)
        self.assertGreater(ctx.discovery_chars, 0)

    def test_model_not_found_is_returned_to_the_model_but_is_not_evidence(self):
        message = "Model 'x_missing' was not found in the indexed knowledge graph. Closest: x_fixture.case"
        ctx = Context({'describe_workflow': Tool(message)})
        content = self.call(ctx, 'describe_workflow', {'model_name': 'x_missing'})
        self.assertIn('Closest', content)
        self.assertFalse(ctx.tool_observations)
        self.assertFalse(ctx.concept.resolved_models)
        self.assertFalse(ctx.concept.is_resolved)

    def test_refused_orm_is_not_evidence(self):
        ctx = Context({'search_read': Tool('ORM read refused: fixture')})
        content = self.call(ctx, 'search_read', {'model': 'x_fixture.case'})
        self.assertFalse(ctx.tool_observations)
        self.assertTrue(ctx.execution_failed)
        self.assertIn('no conclusion', content)

    def test_failed_tool_consumes_budget(self):
        tool = Tool(fail=True)
        ctx = Context({'describe_workflow': tool}, hop_cap=1)
        self.call(ctx, 'describe_workflow')
        self.call(ctx, 'describe_workflow', {'model_name': 'second'})
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual(ctx.hop_count, 1)

    def test_failed_call_is_not_reexecuted(self):
        tool = Tool(fail=True)
        ctx = Context({'describe_workflow': tool})
        self.call(ctx, 'describe_workflow')
        self.call(ctx, 'describe_workflow')
        self.assertEqual(len(tool.calls), 1)

    def test_arguments_are_not_modified_in_place(self):
        tool = Tool()
        ctx = Context({'who_has_access_to': tool})
        arguments = {'model_name': 'x_fixture.case'}
        self.call(ctx, 'who_has_access_to', arguments)
        self.assertNotIn('permission', arguments)
        self.assertEqual(tool.calls[0]['permission'], 'all')

    def test_permission_variants_are_distinct(self):
        tool = Tool()
        ctx = Context({'who_has_access_to': tool})
        for permission in ('read', 'write'):
            self.call(ctx, 'who_has_access_to', {'model_name': 'x_fixture.case', 'permission': permission})
        self.assertEqual(len(tool.calls), 2)

    def test_navigation_cannot_inject_groups(self):
        tool = Tool()
        ctx = Context({'describe_navigation_path': tool})
        self.call(ctx, 'describe_navigation_path', {'user_groups_json': '["forged.admin"]'})
        self.assertEqual(json.loads(tool.calls[0]['user_groups_json']), ['fixture.member'])

    def test_unknown_identity_is_not_empty_groups(self):
        tool = Tool()
        ctx = Context({'describe_navigation_path': tool}, requester_groups_known=False)
        self.call(ctx, 'describe_navigation_path')
        self.assertIsNone(json.loads(tool.calls[0]['user_groups_json']))

    def test_unknown_principal_is_refused(self):
        tool = Tool()
        ctx = Context({'button_execution_path': tool})
        self.call(ctx, 'button_execution_path', {'principal_id': 'forged'})
        self.assertFalse(tool.calls)
        self.assertEqual(ctx.hop_count, 1)

    def test_discovery_and_evidence_share_output_budget(self):
        tool = Tool()
        ctx = Context({'describe_workflow': tool})
        ctx.discovery_chars = 35000
        self.assertIn('Observation budget exhausted', self.call(ctx, 'describe_workflow'))
        self.assertFalse(tool.calls)

    def test_unknown_tool_has_no_evidence(self):
        ctx = Context({})
        self.call(ctx, 'arbitrary_write')
        self.assertFalse(ctx.tool_observations)
        self.assertEqual(ctx.hop_count, 1)

    def test_sensitive_exception_text_is_not_sent_to_model(self):
        ctx = Context({'describe_workflow': Tool(fail=True)})
        self.assertNotIn('sensitive fixture error', self.call(ctx, 'describe_workflow'))


class RequestContextTests(unittest.TestCase):
    def setUp(self):
        self.namespace = functions('code_intelligence/agent/tools/helpers.py', {
            'tool_context', 'get_graph_ref', 'get_llm_ref', 'get_current_question', '_require_graph',
        }, {'contextmanager': contextmanager, 'Optional': __import__('typing').Optional,
            '_graphRef': ContextVar('test_graph', default=None),
            '_llmRef': ContextVar('test_llm', default=None),
            '_currentQuestion': ContextVar('test_question', default=None)})

    def test_nested_context_restores_outer_even_on_exception(self):
        n = self.namespace
        with n['tool_context']('outer', 'outer_llm', 'outer_question'):
            with self.assertRaises(RuntimeError):
                with n['tool_context']('inner', 'inner_llm', 'inner_question'):
                    self.assertEqual(n['_require_graph'](), 'inner')
                    raise RuntimeError('fixture')
            self.assertEqual(n['get_graph_ref'](), 'outer')
            self.assertEqual(n['get_current_question'](), 'outer_question')
        self.assertIsNone(n['get_graph_ref']())
        self.assertIsNone(n['get_llm_ref']())

    def test_concurrent_requests_do_not_share_graph_or_question(self):
        n = self.namespace
        barrier = Barrier(2)
        def request(value):
            with n['tool_context'](value, value, value):
                barrier.wait(timeout=2)
                return n['get_graph_ref'](), n['get_current_question']()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, ['first', 'second']))
        self.assertEqual(results, [('first', 'first'), ('second', 'second')])


class RoutingTests(unittest.TestCase):
    def test_explicit_sources_do_not_import_classifier_or_resolver(self):
        routes = Enum('QueryRoute', {'DOCUMENTARY': 'documentation', 'CODE_INTELLIGENCE': 'system'})
        route = functions('core/routing/routing.py', {'route'}, {
            'RAGState': dict, 'time': time, 'QueryRoute': routes, 'logger': logging.getLogger(__name__),
        })['route']
        self.assertEqual(route({'source_mode': 'systeme'})['route'], 'system')
        self.assertEqual(route({'source_mode': 'documentation'})['route'], 'documentation')

    def test_active_agent_has_no_resolver_planner_or_predispatch(self):
        tree = ast.parse((ROOT / 'code_intelligence/agent/loop.py').read_text())
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertFalse(names & {'resolve_turn', 'generate_investigation_plan', 'run_predispatch_chain'})
        self.assertIn('create_react_agent', names)

    def test_all_system_routes_share_one_node(self):
        source = (ROOT / 'core/graph/graph.py').read_text()
        self.assertNotIn("add_node('orm_agent_loop'", source)
        for name in ('ERP_DATA', 'HYBRID', 'CODE_INTELLIGENCE'):
            self.assertIn(f"QueryRoute.{name}.value: 'code_intelligence_agent'", source)
        self.assertIn("'user_groups': user_groups,", source)

    def test_introspection_has_no_global_graph_access(self):
        source = (ROOT / 'code_intelligence/agent/tools/introspection.py').read_text()
        self.assertNotIn('_GRAPH_REF', source)
        self.assertIn('get_graph_ref()', source)


NATIVE_AVAILABLE = importlib.util.find_spec('langgraph') is not None and importlib.util.find_spec('langchain_core') is not None


@unittest.skipUnless(NATIVE_AVAILABLE, 'Native LangGraph dependencies are not installed')
class NativeAgentSmokeTests(unittest.TestCase):
    def runLoop(self, answerForTurn, maxHops=4):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_core.runnables import RunnableLambda
        from langchain_core.tools import StructuredTool
        from pydantic import PrivateAttr
        class FakeModel(BaseChatModel):
            _turn: int = PrivateAttr(default=0)
            @property
            def _llm_type(self):
                return 'fixture'
            def bind_tools(self, tools, **kwargs):
                return self
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self._turn += 1
                return ChatResult(generations=[ChatGeneration(message=answerForTurn(self._turn, AIMessage))])
        tool = StructuredTool.from_function(
            func=lambda model_name, turn='': 'Real fixture workflow observation', name='describe_workflow',
            description='Inspect a fixture workflow.')
        ctx = Context({tool.name: tool})
        ctx.llm_call_count = 0
        ctx.llm_wait = 0.0
        boundaries = ExecutionBoundaryTests()
        boundaries.setUp()
        namespace = functions('code_intelligence/agent/loop.py', {'run_react_loop'}, {
            'RLock': __import__('threading').RLock, 'tool_context': lambda *args: __import__('contextlib').nullcontext(),
            'SimpleNamespace': SimpleNamespace, 'execute_tool_calls': boundaries.execute,
            'StructuredTool': StructuredTool, 'RunnableLambda': RunnableLambda,
            'SystemMessage': __import__('langchain_core.messages', fromlist=['SystemMessage']).SystemMessage,
            'HumanMessage': __import__('langchain_core.messages', fromlist=['HumanMessage']).HumanMessage,
            'CI_SYSTEM_PROMPT': 'Inspect tools.', 'SYSTEM_INVESTIGATION_PROMPT': '',
            'build_persona_prompt_block': lambda principals: '',
            '_maybe_build_application_layer_reminder': lambda *args: None,
            'invoke_with_rate_limit': lambda model, messages, **kwargs: (model.invoke(messages), 0),
            'CI_MAX_HOPS': maxHops, 'LANGGRAPH_STEP_LIMIT_NOTICE': 'Sorry, need more steps to process this request.',
            'NO_EVIDENCE_ANSWER': 'No evidence',
            'FINAL_MESSAGE_PREVIEW_CHARS': 300,
            'logger': logging.getLogger(__name__),
        })
        return namespace['run_react_loop'](ctx, FakeModel(), []), ctx

    def test_native_loop_executes_guarded_tool_and_returns_final_message(self):
        def answerForTurn(turn, AIMessage):
            return (AIMessage(content='', tool_calls=[{
                'name': 'describe_workflow', 'args': {'model_name': 'x_fixture.case'}, 'id': 'fixture'}])
                if turn == 1 else AIMessage(content='Confirmed fixture observation.'))
        answer, ctx = self.runLoop(answerForTurn)
        self.assertEqual(answer, 'Confirmed fixture observation.')
        self.assertEqual(ctx.hop_count, 1)
        self.assertEqual(ctx.llm_call_count, 2)

    def test_native_loop_allows_ci_max_hops_tool_rounds_before_step_limit(self):
        def answerForTurn(turn, AIMessage):
            return (AIMessage(content='', tool_calls=[{
                'name': 'describe_workflow', 'args': {'model_name': 'x_fixture.case', 'turn': str(turn)},
                'id': f'fixture{turn}'}]) if turn <= 4 else AIMessage(content='Confirmed after four rounds.'))
        answer, ctx = self.runLoop(answerForTurn, maxHops=4)
        self.assertEqual(answer, 'Confirmed after four rounds.')
        self.assertEqual(ctx.hop_count, 4)

    def test_native_loop_never_returns_langgraph_step_limit_notice_as_answer(self):
        def answerForTurn(turn, AIMessage):
            return AIMessage(content='', tool_calls=[{
                'name': 'describe_workflow', 'args': {'model_name': 'x_fixture.case', 'turn': str(turn)},
                'id': f'fixture{turn}'}])
        answer, ctx = self.runLoop(answerForTurn, maxHops=2)
        self.assertNotIn('need more steps', answer)
        self.assertTrue(answer.startswith('Investigation incomplète'))
        self.assertEqual(ctx.fallback_reason, 'incomplete_investigation')

    def test_native_loop_records_reason_and_preview_of_a_discarded_final_message(self):
        answer, ctx = self.runLoop(lambda turn, AIMessage: AIMessage(content='Which model do you mean?'))
        self.assertEqual(answer, 'No evidence')
        self.assertEqual(ctx.fallback_reason, 'no_analysis_observation')
        self.assertEqual(ctx.final_message_preview, 'Which model do you mean?')

    def test_native_loop_records_no_fallback_reason_on_a_supported_answer(self):
        def answerForTurn(turn, AIMessage):
            return (AIMessage(content='', tool_calls=[{
                'name': 'describe_workflow', 'args': {'model_name': 'x_fixture.case'}, 'id': 'fixture'}])
                if turn == 1 else AIMessage(content='Confirmed fixture observation.'))
        _, ctx = self.runLoop(answerForTurn)
        self.assertIsNone(ctx.fallback_reason)


if __name__ == '__main__':
    unittest.main()
