import json
from types import SimpleNamespace

from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.tool_execution import execute_tool_calls
from core.session.reasoning_trace_logger import ReasoningTraceLogger


def readRecords(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def buildContext(logger, tool):
    return DispatchContext(
        G=None, concept=SimpleNamespace(resolved_models=[]), question='q', tool_map={'probe': tool},
        resolved_user_group_xmlids=[], trace_logger=logger, trace_id='t1', hop_cap=5)


def test_log_failure_records_error_type_and_message(tmp_path):
    path = tmp_path / 'trace.jsonl'
    ReasoningTraceLogger(log_filepath=path).log_failure('t1', 'llm_loop', ConnectionError('tunnel offline'))
    record = readRecords(path)[0]
    assert record['record_type'] == 'FAILURE'
    assert (record['stage'], record['error_type'], record['message']) == ('llm_loop', 'ConnectionError', 'tunnel offline')


def test_tool_exception_is_traced_with_tool_name_and_args(tmp_path):
    path = tmp_path / 'trace.jsonl'

    class BrokenTool:
        def invoke(self, arguments):
            raise TimeoutError('slow backend')

    ctx = buildContext(ReasoningTraceLogger(log_filepath=path), BrokenTool())
    messages = []
    execute_tool_calls(ctx, SimpleNamespace(tool_calls=[{'name': 'probe', 'id': 'c1', 'args': {'model_name': 'x.y'}}]), messages)
    record = readRecords(path)[0]
    assert ctx.execution_failed
    assert record['record_type'] == 'FAILURE' and record['stage'] == 'tool'
    assert record['tool_name'] == 'probe' and record['tool_args'] == {'model_name': 'x.y'}
    assert record['error_type'] == 'TimeoutError'


def test_tool_error_output_keeps_its_text_in_the_failure_message(tmp_path):
    path = tmp_path / 'trace.jsonl'

    class RefusingTool:
        def invoke(self, arguments):
            return 'Error: model unknown'

    ctx = buildContext(ReasoningTraceLogger(log_filepath=path), RefusingTool())
    execute_tool_calls(ctx, SimpleNamespace(tool_calls=[{'name': 'probe', 'id': 'c1', 'args': {}}]), [])
    assert 'Error: model unknown' in readRecords(path)[0]['message']
