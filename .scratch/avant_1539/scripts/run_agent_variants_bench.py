#!/usr/bin/env python3
"""
scripts/run_agent_variants_bench.py

Same questions, same number of passes, three agent configurations. Counts how often
the investigation ends with the `no_analysis_observation` fallback (final answer
written without any analysis tool observation).

Variants (investigation loop of the system agent only, no production code modified):
  current   configuration as deployed
  temp06    sampling temperature 0.6 instead of 0.0
  no_think  LLM_NO_THINK_MARKER appended to the system prompt

Usage:
    python scripts/run_agent_variants_bench.py                      # 7 questions x 3 passes x 3 variants
    python scripts/run_agent_variants_bench.py --passes 1           # smoke run
    python scripts/run_agent_variants_bench.py --variants current no_think
    python scripts/run_agent_variants_bench.py --retry-interrupted  # after restoring the tunnel
    python scripts/run_agent_variants_bench.py --fresh              # discard previous results

Each run is appended to captures/agent_variants_bench.jsonl. A rerun skips the runs
already recorded, so an interrupted bench resumes where it stopped. With nothing left
to run, only the report is printed.
"""

import argparse
import contextlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from unittest import mock

projectRoot = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(projectRoot))

import code_intelligence.agent.loop as agentLoop
import config.settings as settings
from code_intelligence.agent.resolution.semantic_retrieval import warm_semantic_index
from code_intelligence.graph import get_code_intelligence_graph
from core.evaluation.preflight import BackendUnavailable, require_backends
from core.evidence.evidence_collector import collect_and_clear_evidence, start_evidence_collection
from core.llm.llm_client import with_no_think
from core.session.reasoning_trace_logger import ReasoningTraceLogger

LANGUAGE = 'fr'
QUESTIONS = {
    'Q01': "comment voir les ventes réalisées ?",
    'Q02': "c'est quoi le protocole pour les ventes ?",
    'Q03': "comment faire une demande d'achat ?",
    'Q04': "qui approuve les congés dans l'ERP ?",
    'Q05': "comment je fais pour créer une facture ?",
    'Q06': "Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?",
    'Q07': "Pourquoi un vendeur simple ne peut-il pas cliquer sur « Unlock » sur un Sales Order verrouillé, "
           "même si c'est lui qui l'a confirmé ?",
}
VARIANT_NAMES = ['current', 'temp06', 'no_think']
TEMPERATURE = 0.6
FALLBACK = 'no_analysis_observation'
ANSWERED = 'answered'
INFRA_OUTCOMES = ('interrupted', 'error')
MAX_CONSECUTIVE_INFRA_FAILURES = 3
RESULTS_PATH = projectRoot / 'captures' / 'agent_variants_bench.jsonl'


def variant_patch(name):
    """In-memory configuration of one variant, active only inside the `with` block."""
    if name == 'temp06':
        build = agentLoop.get_chat_llm
        return mock.patch.object(agentLoop, 'get_chat_llm', lambda **kwargs: build(**{**kwargs, 'temperature': TEMPERATURE}))
    if name == 'no_think':
        return mock.patch.object(agentLoop, 'SYSTEM_INVESTIGATION_PROMPT', with_no_think(agentLoop.SYSTEM_INVESTIGATION_PROMPT))
    return contextlib.nullcontext()


@contextlib.contextmanager
def capture_summaries(summaries):
    """Collect the SUMMARY record the agent logs for the question (file output unchanged)."""
    original = ReasoningTraceLogger.log_summary

    def record(self, *args, **kwargs):
        summary = original(self, *args, **kwargs)
        summaries.append(summary)
        return summary

    with mock.patch.object(ReasoningTraceLogger, 'log_summary', record):
        yield


def run_once(question):
    summaries, error = [], None
    startedAt = time.time()
    start_evidence_collection()
    try:
        with capture_summaries(summaries):
            agentLoop.code_intelligence_agent({'question': question, 'chat_history': [], 'language': LANGUAGE})
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'[:300]
    finally:
        collect_and_clear_evidence()
    summary = summaries[-1] if summaries else None
    return {
        'fallback_reason': summary.fallback_reason if summary else None,
        'hop_count': summary.hop_count if summary else 0,
        'llm_call_count': summary.llm_call_count if summary else 0,
        'seconds': round(time.time() - startedAt, 1),
        'error': error or (None if summary else 'no summary logged'),
    }


def outcome(record):
    return 'error' if record['error'] else record['fallback_reason'] or ANSWERED


def run_key(record):
    return record['variant'], record['question_id'], record['pass_number']


def load_runs(path):
    """Latest record of every (variant, question, pass); a retried run replaces the failed one."""
    if not path.exists():
        return {}
    with open(path, encoding='utf-8') as file:
        return {run_key(record): record for record in map(json.loads, filter(str.strip, file))}


def pending_runs(variants, passes, runs, retryInfra):
    """Runs left to do, pass by pass; the variant order rotates so none is always first."""
    for passNumber in range(1, passes + 1):
        for index, (questionId, question) in enumerate(QUESTIONS.items()):
            shift = (index + passNumber) % len(variants)
            for variant in variants[shift:] + variants[:shift]:
                previous = runs.get((variant, questionId, passNumber))
                if previous is None or (retryInfra and outcome(previous) in INFRA_OUTCOMES):
                    yield (variant, questionId, passNumber), question


def warm_up():
    graph = get_code_intelligence_graph(translation_languages=[LANGUAGE], request_language=LANGUAGE)
    print(f'Graph and semantic index ready: {[status.value for status in warm_semantic_index(graph, [LANGUAGE])]}')


def execute(todo, runs):
    """Run the pending runs, appending each result. Returns False when the backend looks down."""
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    consecutiveFailures = 0
    for number, ((variant, questionId, passNumber), question) in enumerate(todo, 1):
        with variant_patch(variant):
            result = run_once(question)
        record = {'variant': variant, 'question_id': questionId, 'pass_number': passNumber,
                  'model': settings.LOCAL_LLM_MODEL, **result}
        with open(RESULTS_PATH, 'a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')
        runs[run_key(record)] = record
        print(f'[{number}/{len(todo)}] {variant:<9} {questionId} pass {passNumber}: '
              f'{outcome(record)} ({record["seconds"]}s)', flush=True)
        consecutiveFailures = consecutiveFailures + 1 if outcome(record) in INFRA_OUTCOMES else 0
        if consecutiveFailures >= MAX_CONSECUTIVE_INFRA_FAILURES:
            print(f'{consecutiveFailures} consecutive interrupted/error runs: the backend looks down. '
                  'Restore it, then rerun with --retry-interrupted.')
            return False
    return True


def variant_stats(records):
    outcomes = Counter(outcome(record) for record in records)
    infra = sum(outcomes[name] for name in INFRA_OUTCOMES)
    valid = [record for record in records if not record['error']]

    def average(field):
        return round(sum(record[field] for record in valid) / len(valid), 1) if valid else 0.0

    return {
        'runs': len(records),
        'fallback': outcomes[FALLBACK],
        'answered': outcomes[ANSWERED],
        'infra': infra,
        'other': len(records) - outcomes[FALLBACK] - outcomes[ANSWERED] - infra,
        'hops': average('hop_count'),
        'llm_calls': average('llm_call_count'),
        'seconds': average('seconds'),
    }


def print_report(runs, variants):
    records = list(runs.values())
    present = [variant for variant in variants if any(record['variant'] == variant for record in records)]
    if not present:
        print('No result recorded.')
        return
    print(f'\n{FALLBACK} rate (interrupted/error runs are counted in the runs but are not decisions of the model)')
    print(f'{"variant":<10}{"runs":>5}{"fallback":>10}{"rate":>7}{"answered":>10}{"other":>7}{"infra":>7}'
          f'{"hops":>7}{"llm":>6}{"sec":>8}')
    for variant in present:
        stats = variant_stats([record for record in records if record['variant'] == variant])
        print(f'{variant:<10}{stats["runs"]:>5}{stats["fallback"]:>10}{stats["fallback"] / stats["runs"]:>7.0%}'
              f'{stats["answered"]:>10}{stats["other"]:>7}{stats["infra"]:>7}'
              f'{stats["hops"]:>7}{stats["llm_calls"]:>6}{stats["seconds"]:>8}')
    print(f'\nfallbacks per question (over the passes done)\n{"question":<10}' + ''.join(f'{variant:>10}' for variant in present))
    for questionId in QUESTIONS:
        cells = []
        for variant in present:
            rows = [record for record in records if record['variant'] == variant and record['question_id'] == questionId]
            cells.append(f'{sum(outcome(record) == FALLBACK for record in rows)}/{len(rows)}')
        print(f'{questionId:<10}' + ''.join(f'{cell:>10}' for cell in cells))


def main():
    parser = argparse.ArgumentParser(description='Compare agent configurations on the no_analysis_observation fallback rate.')
    parser.add_argument('--passes', type=int, default=3, help='passes over the questions (default 3)')
    parser.add_argument('--variants', nargs='+', choices=VARIANT_NAMES, default=VARIANT_NAMES)
    parser.add_argument('--retry-interrupted', action='store_true', help='rerun the runs recorded as interrupted or error')
    parser.add_argument('--fresh', action='store_true', help='discard the recorded results first')
    args = parser.parse_args()

    if 'no_think' in args.variants and not settings.LLM_NO_THINK_MARKER:
        print(f'[SKIP] No no-think marker for model {settings.LOCAL_LLM_MODEL} (LLM_NO_THINK_MARKER is empty).')
        return 2
    if args.fresh:
        RESULTS_PATH.unlink(missing_ok=True)
    runs = load_runs(RESULTS_PATH)
    todo = list(pending_runs(args.variants, args.passes, runs, args.retry_interrupted))
    completed = True
    if todo:
        try:
            require_backends()
        except BackendUnavailable as error:
            print(f'[SKIP] Inference backend unavailable, nothing run: {error}')
            return 2
        warm_up()
        print(f'{len(todo)} run(s) to do, model {settings.LOCAL_LLM_MODEL}')
        completed = execute(todo, runs)
    print_report(runs, args.variants)
    return 0 if completed else 3


if __name__ == '__main__':
    sys.exit(main())
