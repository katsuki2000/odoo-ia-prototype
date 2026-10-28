#!/usr/bin/env python3
"""
scripts/run_rag_model_eval.py

Compare LLMs on the answer generation of the documentary RAG, on tests/rag_eval_questions.json.
Every model answers from the same retrieved passages, cached in captures/rag_eval_contexts.json.
One process per model; each result is appended to captures/rag_model_eval.jsonl, so an interrupted
run resumes where it stopped. The measures need no judge model; the answers are kept for reading.

    python scripts/run_rag_model_eval.py --model qwen3:14b
    python scripts/run_rag_model_eval.py --model gpt-oss:20b --passes 3
    python scripts/run_rag_model_eval.py --model mistral-small3.2:24b
    python scripts/run_rag_model_eval.py --model qwen3:8b
    python scripts/run_rag_model_eval.py --model qwen3:30b-a3b
    python scripts/run_rag_model_eval.py --report

fact_recall is a strict lower bound: a correct paraphrase that omits the exact wording of a fact
counts as missing. abstained is a keyword heuristic. The semantic judgement is left to RAGAS.
All candidates use the same cached retrieval contexts and are required to report the same
Ollama context length; raw answers are retained for qualitative review.
"""

import argparse
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path

import requests

projectRoot = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(projectRoot))

from core.evaluation import run_store as runStore
from core.evaluation.ollama_server import model_override, prepare_server, set_keep_alive
from core.evaluation.preflight import BackendUnavailable, require_backends
from core.graph.graph_nodes import retrieve
from core.routing.routing_keywords import _fold_accents
from document_rag.generate_node import generate

QUESTIONS_PATH = projectRoot / 'tests' / 'rag_eval_questions.json'
CONTEXTS_PATH = projectRoot / 'captures' / 'rag_eval_contexts.json'
RESULTS_PATH = projectRoot / 'captures' / 'rag_model_eval.jsonl'
MAX_CONSECUTIVE_ERRORS = 3
GENERATION_ERROR_PREFIX = 'Désolé, une erreur'


def normalize(text):
    """Case, accent, whitespace and markdown-emphasis insensitive form used to find a fact in an answer."""
    return re.sub(r'[\s*`]+', '', _fold_accents(text.casefold()).replace('’', "'"))


ABSTENTION_MARKERS = tuple(normalize(marker) for marker in (
    'pas trouvé cette information', 'pas de source fiable', 'aucune information',
    'pas documenté', 'pas précisé', 'pas mentionné', 'ne fait pas partie de mon périmètre',
))


def load_questions(ids):
    with open(QUESTIONS_PATH, encoding='utf-8') as file:
        questions = json.load(file)['questions']
    return [item for item in questions if not ids or item['id'] in ids]


def load_contexts(questions, refresh):
    """Retrieved passages per question id, retrieved once and reused by every model."""
    cached = json.loads(CONTEXTS_PATH.read_text(encoding='utf-8')) if CONTEXTS_PATH.exists() else {}
    stale = [item for item in questions if refresh or cached.get(item['id'], {}).get('question') != item['question']]
    for item in stale:
        chunks = retrieve({'question': item['question']})['retrieved_chunks']
        if not chunks:
            raise BackendUnavailable(f'retrieval returned no passage for {item["id"]}')
        cached[item['id']] = {'question': item['question'], 'chunks': chunks}
    if stale:
        CONTEXTS_PATH.parent.mkdir(exist_ok=True)
        CONTEXTS_PATH.write_text(json.dumps(cached, ensure_ascii=False), encoding='utf-8')
    return {item['id']: cached[item['id']]['chunks'] for item in questions}


def score(item, answer, citedSources):
    folded = normalize(answer)
    facts, references = item['facts'], item['reference_sources']
    return {
        'fact_recall': sum(normalize(fact) in folded for fact in facts) / len(facts) if facts else None,
        'source_recall': len(set(references) & set(citedSources)) / len(references) if references else None,
        'abstained': any(marker in folded for marker in ABSTENTION_MARKERS),
    }


def require_context_length(serverInfo, expected):
    actual = serverInfo.get('context_length')
    if actual != expected:
        raise BackendUnavailable(
            f'Expected Ollama context length {expected}, got {actual!r}; '
            'set OLLAMA_CONTEXT_LENGTH consistently before comparing models.'
        )


def run_once(item, chunks):
    answer, citedSources, confidence, llmCalls, structuredFailed, error = '', [], None, 0, False, None
    startedAt = time.time()
    try:
        result = generate({'question': item['question'], 'retrieved_chunks': chunks, 'timing': {}})
        response = result['response']
        answer, confidence = response.answer, response.confidence
        citedSources = [source.title for source in response.sources]
        llmCalls = result['timing'].get('llm_call_count', 0)
        structuredFailed = bool(result.get('sources_fallback_eligible'))
        error = answer if answer.startswith(GENERATION_ERROR_PREFIX) else None
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    return {
        'answer': answer,
        'answer_chars': len(answer),
        'cited_sources': citedSources,
        'confidence': confidence,
        'llm_calls': llmCalls,
        'structured_failed': structuredFailed,
        'seconds': round(time.time() - startedAt, 1),
        'error': error[:300] if error else None,
        **score(item, answer, citedSources),
    }


def describe(record):
    if record['error']:
        return 'error'
    if record['fact_recall'] is None:
        return 'abstained' if record['abstained'] else 'ANSWERED (unanswerable question)'
    return f'facts {record["fact_recall"]:.0%}, sources {record["source_recall"]:.0%}'


def execute(todo, runs, model, serverInfo, chunksById):
    """Run the pending questions, appending each result. Returns False when the backend looks down."""
    consecutiveErrors = 0
    for number, (item, passNumber) in enumerate(todo, 1):
        record = {
            'model': model, 'question_id': item['id'], 'pass_number': passNumber,
            'category': item['category'], 'answerable': item['answerable'],
            **serverInfo, **run_once(item, chunksById[item['id']]),
        }
        runStore.append_run(RESULTS_PATH, record)
        runs[runStore.run_key(record)] = record
        print(f'[{number}/{len(todo)}] {item["id"]} pass {passNumber}: {describe(record)} ({record["seconds"]}s)', flush=True)
        consecutiveErrors = consecutiveErrors + 1 if record['error'] else 0
        if consecutiveErrors >= MAX_CONSECUTIVE_ERRORS:
            print(f'{consecutiveErrors} consecutive generation errors: the backend looks down. '
                  'Restore it, then rerun with --retry-errors.')
            return False
    return True


def mean(values):
    return statistics.mean(values) if values else None


def model_stats(records):
    valid = [record for record in records if not record['error']]
    answerable = [record for record in valid if record['answerable']]
    unanswerable = [record for record in valid if not record['answerable']]
    seconds = sorted(record['seconds'] for record in valid)
    return {
        'runs': len(records),
        'errors': len(records) - len(valid),
        'facts': mean([record['fact_recall'] for record in answerable]),
        'complete': mean([record['fact_recall'] == 1 for record in answerable]),
        'sources': mean([record['source_recall'] for record in answerable if record['source_recall'] is not None]),
        'refused': mean([record['abstained'] for record in answerable]),
        'abstained': mean([record['abstained'] for record in unanswerable]),
        'structured_failed': mean([record['structured_failed'] for record in valid]),
        'confidence': mean([record['confidence'] for record in valid if record.get('confidence') is not None]),
        'answer_chars': mean([record.get('answer_chars', len(record.get('answer', ''))) for record in valid]),
        'p50': statistics.median(seconds) if seconds else None,
        'p90': seconds[math.ceil(0.9 * len(seconds)) - 1] if seconds else None,
        'vram': min((record['vram_fraction'] for record in records if record.get('vram_fraction') is not None), default=None),
    }


def pct(value):
    return 'n/a' if value is None else f'{value:.0%}'


def seconds_text(value):
    return 'n/a' if value is None else f'{value:.0f}'


def question_cell(rows):
    valid = [row for row in rows if not row['error']]
    if not valid:
        return '-'
    if valid[0]['answerable']:
        return pct(mean([row['fact_recall'] for row in valid]))
    return f'{sum(row["abstained"] for row in valid)}/{len(valid)} abst.'


def print_report(runs):
    records = list(runs.values())
    models = sorted({record['model'] for record in records})
    if not models:
        print('No result recorded.')
        return
    print('\nDocumentary RAG answers per model (error runs are excluded from the rates)')
    print(f'{"model":<22}{"runs":>5}{"err":>5}{"facts":>7}{"full":>7}{"src":>7}{"refus":>7}{"trap":>7}{"rawfb":>7}{"conf":>7}{"chars":>7}{"p50s":>7}{"p90s":>7}{"vram":>6}')
    for model in models:
        stats = model_stats([record for record in records if record['model'] == model])
        vram = 'n/a' if stats['vram'] is None else f'{stats["vram"]:.2f}'
        print(f'{model:<22}{stats["runs"]:>5}{stats["errors"]:>5}{pct(stats["facts"]):>7}{pct(stats["complete"]):>7}'
              f'{pct(stats["sources"]):>7}{pct(stats["refused"]):>7}{pct(stats["abstained"]):>7}{pct(stats["structured_failed"]):>7}'
              f'{pct(stats["confidence"]):>7}{seconds_text(stats["answer_chars"]):>7}'
              f'{seconds_text(stats["p50"]):>7}{seconds_text(stats["p90"]):>7}{vram:>6}')
    print('\nfacts = mean share of the expected facts found; full = answers with every fact; src = expected sources cited;')
    print('refus = answerable questions where the model abstained; trap = unanswerable questions where it abstained;')
    print('rawfb = structured output failed (raw reply parsed); conf = model-declared confidence (diagnostic only);')
    print('chars = mean answer length; vram < 1.00 means CPU offload (latency not comparable).')
    print(f'\nper question (over the passes done)\n{"question":<12}' + ''.join(f'{model[:20]:>22}' for model in models))
    for questionId in dict.fromkeys(record['question_id'] for record in records):
        cells = [question_cell([record for record in records if record['model'] == model and record['question_id'] == questionId])
                 for model in models]
        print(f'{questionId:<12}' + ''.join(f'{cell:>22}' for cell in cells))


def main():
    parser = argparse.ArgumentParser(description='Compare LLMs on the answer generation of the documentary RAG.')
    parser.add_argument('--model', help='Ollama model name, as listed by `ollama list`')
    parser.add_argument('--ids', nargs='+', help='restrict to these question ids')
    parser.add_argument('--passes', type=int, default=3, help='generation repetitions per question (default: 3)')
    parser.add_argument('--context-length', type=int, default=32768,
                        help='required Ollama context length for a fair comparison (default: 32768)')
    parser.add_argument('--retry-errors', action='store_true', help='rerun the runs recorded as error')
    parser.add_argument('--fresh', action='store_true', help='discard the recorded results of this model first')
    parser.add_argument('--refresh-contexts', action='store_true', help='retrieve the passages again')
    parser.add_argument('--keep-loaded', action='store_true', help='do not unload the model at the end')
    parser.add_argument('--report', action='store_true', help='print the comparison of the recorded results and exit')
    args = parser.parse_args()

    if args.report:
        print_report(runStore.load_runs(RESULTS_PATH))
        return 0
    if not args.model:
        parser.error('--model is required unless --report is given')
    if args.passes < 1:
        parser.error('--passes must be at least 1')
    if args.context_length < 1:
        parser.error('--context-length must be at least 1')

    questions = load_questions(args.ids)
    if not questions:
        print('[ERROR] No question matches the filters.')
        return 1
    if args.fresh:
        runStore.discard_model(RESULTS_PATH, args.model)
    runs = runStore.load_runs(RESULTS_PATH)
    todo = list(runStore.pending_runs(args.model, questions, args.passes, runs,
                                      lambda previous: args.retry_errors and bool(previous['error'])))
    if not todo:
        print_report(runs)
        return 0

    try:
        chunksById = load_contexts(questions, args.refresh_contexts)
        serverInfo = prepare_server(args.model)
    except (BackendUnavailable, requests.RequestException) as error:
        print(f'[SKIP] {error}')
        return 2
    print(f'{args.model} loaded: {serverInfo}')
    finished = False
    try:
        require_context_length(serverInfo, args.context_length)
        with model_override(args.model):
            require_backends()
            finished = execute(todo, runs, args.model, serverInfo, chunksById)
    except BackendUnavailable as error:
        print(f'[SKIP] Backend unavailable, no run started: {error}')
    finally:
        if not args.keep_loaded:
            set_keep_alive(args.model, 0)
    print_report(runs)
    return 0 if finished else 3


if __name__ == '__main__':
    sys.exit(main())
