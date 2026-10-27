#!/usr/bin/env python3
"""
scripts/run_model_decision_bench.py

Compare LLMs on the tool calling of the investigation agent, on the question banks
of run_bloc_n1_benchmark.py. One process per model; each result is appended to
captures/model_decision_bench.jsonl, so an interrupted run resumes where it stopped.

    python scripts/run_model_decision_bench.py --model qwen3:14b
    python scripts/run_model_decision_bench.py --model gpt-oss:20b --passes 2
    python scripts/run_model_decision_bench.py --report

The requester identity is the service account of run_bloc_n1_benchmark.py. The answers are
kept in the results file for the human review of the finalists.
"""

import argparse
import contextlib
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from unittest import mock

import langgraph.prebuilt
import requests
from langchain_core.messages import AIMessage, ToolMessage

projectRoot = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(projectRoot))

import config.settings as settings
import core.llm.llm_client as llmClient
from code_intelligence.agent.resolution.semantic_retrieval import warm_semantic_index
from code_intelligence.graph import get_code_intelligence_graph
from code_intelligence.rules.common import NOT_FOUND_MARKER
from core.evaluation.preflight import BackendUnavailable, require_backends
from core.evidence.evidence_collector import collect_and_clear_evidence, start_evidence_collection
from core.graph.graph import code_intelligence_agent
from run_agent_variants_bench import FALLBACK, INFRA_OUTCOMES, MAX_CONSECUTIVE_INFRA_FAILURES, capture_summaries, outcome
from run_bloc_n1_benchmark import (
    _extract_tools_used,
    bind_requester_identity,
    build_agent_state,
    load_questions,
    read_installed_modules,
)

DEFAULT_BANKS = ['native_n1', 'custom_b9']
RESULTS_PATH = projectRoot / 'captures' / 'model_decision_bench.jsonl'
SERVER_TIMEOUT_SECONDS = 900
OBSERVATION_KINDS = {
    'invalid': ('Tool unavailable.',),
    'failed': ('Error executing',),
    'duplicate': ('Already executed',),
    'refused': ('Refused:',),
    'budget': ('Investigation tool budget exhausted.', 'Observation budget exhausted.'),
}


def server_call(method, path, payload=None):
    url = f'{settings.LLM_BASE_URL.removesuffix("/v1")}{path}'
    response = requests.request(method, url, json=payload, timeout=SERVER_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json() if response.content else {}


def loaded_models():
    return {entry['name']: entry for entry in server_call('GET', '/api/ps').get('models', [])}


def set_keep_alive(model, keepAlive):
    server_call('POST', '/api/generate', {'model': model, 'keep_alive': keepAlive, 'stream': False})


def require_tool_support(model):
    try:
        capabilities = server_call('POST', '/api/show', {'model': model}).get('capabilities')
    except requests.HTTPError as error:
        raise BackendUnavailable(f'{model} is not available on the server ({error}); pull it first.')
    if capabilities is not None and 'tools' not in capabilities:
        raise BackendUnavailable(f'{model} does not declare tool support (capabilities: {capabilities}).')


def prepare_server(model):
    """Free the GPU of the other chat models, load the candidate; return how it was loaded."""
    require_tool_support(model)
    for name in loaded_models():
        if name not in (model, settings.EMBEDDING_MODEL):
            set_keep_alive(name, 0)
    set_keep_alive(model, -1)
    entry = loaded_models().get(model, {})
    return {
        'vram_fraction': round(entry['size_vram'] / entry['size'], 2) if entry.get('size') else None,
        'context_length': entry.get('context_length'),
    }


@contextlib.contextmanager
def model_override(model):
    marker = '/no_think' if model.lower().startswith('qwen3') else ''
    with contextlib.ExitStack() as stack:
        for module in (settings, llmClient):
            stack.enter_context(mock.patch.object(module, 'LLM_MODEL', model))
            stack.enter_context(mock.patch.object(module, 'LLM_NO_THINK_MARKER', marker))
        yield


class RecordingAgent:
    def __init__(self, agent, box):
        self.agent, self.box = agent, box

    def invoke(self, *args, **kwargs):
        result = self.agent.invoke(*args, **kwargs)
        self.box.append(result['messages'])
        return result


@contextlib.contextmanager
def capture_agent_messages(box):
    build = langgraph.prebuilt.create_react_agent
    with mock.patch.object(langgraph.prebuilt, 'create_react_agent', lambda *a, **k: RecordingAgent(build(*a, **k), box)):
        yield


def classify(message):
    content = str(message.content)
    if message.status == 'error':
        return 'invalid'
    for kind, prefixes in OBSERVATION_KINDS.items():
        if content.startswith(prefixes):
            return kind
    return 'not_found' if NOT_FOUND_MARKER in content else 'ok'


def tool_call_stats(messages):
    attempted = [call['name'] for message in messages if isinstance(message, AIMessage) for call in message.tool_calls]
    results = Counter(classify(message) for message in messages if isinstance(message, ToolMessage))
    return attempted, dict(results)


def run_once(item):
    summaries, agentMessages, error, answer, toolsUsed = [], [], None, '', []
    startedAt = time.time()
    start_evidence_collection()
    try:
        with capture_summaries(summaries), capture_agent_messages(agentMessages):
            result = code_intelligence_agent(build_agent_state(item))
        response = result.get('response')
        answer = response.answer if response else result.get('raw_answer', '')
        toolsUsed = _extract_tools_used(response.sources or []) if response else []
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'[:300]
    finally:
        collect_and_clear_evidence()
    summary = summaries[-1] if summaries else None
    attempted, results = tool_call_stats(agentMessages[-1]) if agentMessages else ([], {})
    return {
        'answer': answer,
        'tools_used': toolsUsed,
        'missing_tools': sorted(set(item.get('expected_tools', [])) - set(toolsUsed)),
        'tools_attempted': attempted,
        'tool_results': results,
        'fallback_reason': summary.fallback_reason if summary else None,
        'hop_count': summary.hop_count if summary else 0,
        'llm_call_count': summary.llm_call_count if summary else 0,
        'seconds': round(time.time() - startedAt, 1),
        'error': error or (None if summary else 'no summary logged'),
    }


def run_key(record):
    return record['model'], record['question_id'], record['pass_number']


def load_runs():
    if not RESULTS_PATH.exists():
        return {}
    with open(RESULTS_PATH, encoding='utf-8') as file:
        return {run_key(record): record for record in map(json.loads, filter(str.strip, file))}


def discard_model(model):
    kept = [record for key, record in load_runs().items() if key[0] != model]
    with open(RESULTS_PATH, 'w', encoding='utf-8') as file:
        file.writelines(json.dumps(record, ensure_ascii=False) + '\n' for record in kept)


def pending_runs(model, questions, passes, runs, retryInfra):
    for passNumber in range(1, passes + 1):
        for item in questions:
            previous = runs.get((model, item['id'], passNumber))
            if previous is None or (retryInfra and outcome(previous) in INFRA_OUTCOMES):
                yield item, passNumber


def warm_up(questions):
    for language in sorted({item['language'] for item in questions if item.get('language')}):
        graph = get_code_intelligence_graph(translation_languages=[language], request_language=language)
        print(f'Graph and semantic index ready ({language}): {[status.value for status in warm_semantic_index(graph, [language])]}')


def execute(todo, runs, model, serverInfo):
    """Run the pending questions, appending each result. Returns False when the backend looks down."""
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    consecutiveFailures = 0
    for number, (item, passNumber) in enumerate(todo, 1):
        record = {
            'model': model, 'bank': item['bank'], 'question_id': item['id'], 'pass_number': passNumber,
            'capability': item['capability'], 'expected_tools': item.get('expected_tools', []),
            **serverInfo, **run_once(item),
        }
        with open(RESULTS_PATH, 'a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')
        runs[run_key(record)] = record
        print(f'[{number}/{len(todo)}] {item["id"]} pass {passNumber}: {outcome(record)}, '
              f'missing tools {record["missing_tools"] or "none"} ({record["seconds"]}s)', flush=True)
        consecutiveFailures = consecutiveFailures + 1 if outcome(record) in INFRA_OUTCOMES else 0
        if consecutiveFailures >= MAX_CONSECUTIVE_INFRA_FAILURES:
            print(f'{consecutiveFailures} consecutive interrupted/error runs: the backend looks down. '
                  'Restore it, then rerun with --retry-interrupted.')
            return False
    return True


def model_stats(records):
    valid = [record for record in records if not record['error'] and outcome(record) != 'interrupted']
    calls = Counter()
    for record in valid:
        calls.update(record['tool_results'])
    seconds = sorted(record['seconds'] for record in valid)
    total = sum(calls.values())

    def rate(count, whole):
        return count / whole if whole else 0.0

    return {
        'runs': len(records),
        'infra': len(records) - len(valid),
        'coverage': rate(sum(not record['missing_tools'] for record in valid), len(valid)),
        'fallback': rate(sum(record['fallback_reason'] == FALLBACK for record in valid), len(valid)),
        'calls': total,
        'ok': rate(calls['ok'], total),
        'bad': calls['invalid'] + calls['failed'],
        'not_found': calls['not_found'],
        'hops': statistics.mean(record['hop_count'] for record in valid) if valid else 0.0,
        'p50': statistics.median(seconds) if seconds else 0.0,
        'p90': seconds[math.ceil(0.9 * len(seconds)) - 1] if seconds else 0.0,
        'vram': min((record['vram_fraction'] for record in records if record.get('vram_fraction') is not None), default=None),
    }


def print_report(runs):
    records = list(runs.values())
    models = sorted({record['model'] for record in records})
    if not models:
        print('No result recorded.')
        return
    print('\nTool calling per model (interrupted and error runs are excluded from the rates)')
    print(f'{"model":<22}{"runs":>5}{"infra":>6}{"cover":>7}{"fallbk":>8}{"calls":>6}{"ok":>6}{"bad":>5}{"nf":>4}{"hops":>6}{"p50s":>7}{"p90s":>7}{"vram":>6}')
    for model in models:
        stats = model_stats([record for record in records if record['model'] == model])
        vram = f'{stats["vram"]:.2f}' if stats['vram'] is not None else 'n/a'
        print(f'{model:<22}{stats["runs"]:>5}{stats["infra"]:>6}{stats["coverage"]:>7.0%}{stats["fallback"]:>8.0%}'
              f'{stats["calls"]:>6}{stats["ok"]:>6.0%}{stats["bad"]:>5}{stats["not_found"]:>4}{stats["hops"]:>6.1f}'
              f'{stats["p50"]:>7.0f}{stats["p90"]:>7.0f}{vram:>6}')
    print('\ncover = questions with every expected tool used; fallbk = no_analysis_observation; ok = valid tool calls;')
    print('bad = invalid or failed calls; nf = identifiers absent from the graph; vram < 1.00 means CPU offload (latency not comparable).')
    print(f'\nexpected tools covered per question (over the passes done)\n{"question":<12}' + ''.join(f'{model[:20]:>22}' for model in models))
    for questionId in dict.fromkeys(record['question_id'] for record in records):
        cells = []
        for model in models:
            rows = [record for record in records if record['model'] == model and record['question_id'] == questionId]
            cells.append(f'{sum(not row["missing_tools"] and not row["error"] for row in rows)}/{len(rows)}')
        print(f'{questionId:<12}' + ''.join(f'{cell:>22}' for cell in cells))


def main():
    parser = argparse.ArgumentParser(description='Compare LLMs on the tool calling of the investigation agent.')
    parser.add_argument('--model', help='Ollama model name, as listed by `ollama list`')
    parser.add_argument('--bank', nargs='+', default=DEFAULT_BANKS, help=f'question banks (default {DEFAULT_BANKS})')
    parser.add_argument('--ids', nargs='+', help='restrict to these question ids')
    parser.add_argument('--passes', type=int, default=1)
    parser.add_argument('--retry-interrupted', action='store_true', help='rerun the runs recorded as interrupted or error')
    parser.add_argument('--fresh', action='store_true', help='discard the recorded results of this model first')
    parser.add_argument('--keep-loaded', action='store_true', help='do not unload the model at the end')
    parser.add_argument('--report', action='store_true', help='print the comparison of the recorded results and exit')
    args = parser.parse_args()

    if args.report:
        print_report(load_runs())
        return 0
    if not args.model:
        parser.error('--model is required unless --report is given')

    questions, _ = load_questions(args.ids, None, args.bank, read_installed_modules())
    if not questions:
        print('[ERROR] No question matches the filters.')
        return 1
    if args.fresh:
        discard_model(args.model)
    runs = load_runs()
    todo = list(pending_runs(args.model, questions, args.passes, runs, args.retry_interrupted))
    if not todo:
        print_report(runs)
        return 0

    try:
        serverInfo = prepare_server(args.model)
    except (BackendUnavailable, requests.RequestException) as error:
        print(f'[SKIP] {error}')
        return 2
    print(f'{args.model} loaded: {serverInfo}')
    finished = False
    try:
        with model_override(args.model):
            require_backends()
            bind_requester_identity()
            warm_up(questions)
            finished = execute(todo, runs, args.model, serverInfo)
    except BackendUnavailable as error:
        print(f'[SKIP] Backend unavailable, no run started: {error}')
    finally:
        if not args.keep_loaded:
            set_keep_alive(args.model, 0)
    print_report(runs)
    return 0 if finished else 3


if __name__ == '__main__':
    sys.exit(main())
