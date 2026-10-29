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
    python scripts/run_rag_model_eval.py --model qwen3:14b --reasoning-effort none
    python scripts/run_rag_model_eval.py --report

--reasoning-effort sends that value with the generation request (RAG_REASONING_EFFORT; `none` switches the
reasoning off on models that support it); the results are recorded as `<model>+reasoning_<value>` so they sit
beside the default run of the same model.

fact_recall is the share of the key values of the question (number, name, command) found in the answer.
Scores are recomputed from the stored answers at each load, so editing the facts needs no new run.
abstained is a keyword heuristic, true when the answer says the information was not found and gives none of the
expected facts. The semantic judgement is left to RAGAS.
All candidates use the same cached retrieval contexts and are required to report the same
Ollama context length; raw answers are retained for qualitative review.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from unittest import mock

import requests

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import config.settings as settings
from core.evaluation import run_store
from core.evaluation.bench_common import (
    contains_fact, execute_runs, latency_percentiles, mean, normalize, pct, rescore_runs, run_on_model, seconds_text,
)
from core.evaluation.preflight import BackendUnavailable
from core.graph.graph_nodes import retrieve
from document_rag.generate_node import generate

QUESTIONS_PATH = project_root / 'tests' / 'rag_eval_questions.json'
CONTEXTS_PATH = project_root / 'captures' / 'rag_eval_contexts.json'
RESULTS_PATH = project_root / 'captures' / 'rag_model_eval.jsonl'
GENERATION_ERROR_PREFIX = 'Sorry, an error'
REASONING_SUFFIX = '+reasoning_'


# Matched on normalize() output: lowercase, no accent, no space. Models word a refusal in their own way
# ("pas trouvé cette information", "pas trouvé d'information", "aucun plafond ... n'est mentionné"), so the
# pattern covers the family and not only the sentence the prompt suggests.
ABSTENTION_PATTERN = re.compile('|'.join((
    r"pastrouve(?:cette|d'|del')?information", r'pasdesourcefiable', r'noreliablesource', r'aucune?(?:information|mention)',
    r"n'est(?:pas)?(?:mentionne|precise|indique|documente)", r'ne(?:mentionne|precise|documente)(?:nt)?pas', r'ne(?:contient|contiennent)pas',
    r'pas(?:documente|precise|mentionne)', r'nefaitpaspartiedemonperimetre', r'outsidemyscope',
)))


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


def score(item, answer, cited_sources):
    folded = normalize(answer)
    facts, references = item['facts'], item['reference_sources']
    fact_recall = sum(contains_fact(folded, fact) for fact in facts) / len(facts) if facts else None
    return {
        'fact_recall': fact_recall,
        'source_recall': len(set(references) & set(cited_sources)) / len(references) if references else None,
        'abstained': ABSTENTION_PATTERN.search(folded) is not None and not fact_recall,
    }


def load_scored_runs():
    """Recorded runs, scores recomputed from the stored answers with the current question set."""
    return rescore_runs(run_store.load_runs(RESULTS_PATH), load_questions(None),
                        lambda item, record: score(item, record['answer'], record['cited_sources']))


def run_once(item, chunks):
    answer, cited_sources, confidence, llm_calls, structured_failed, error = '', [], None, 0, False, None
    started_at = time.time()
    try:
        result = generate({'question': item['question'], 'retrieved_chunks': chunks, 'timing': {}})
        response = result['response']
        answer, confidence = response.answer, response.confidence
        cited_sources = [source.title for source in response.sources]
        llm_calls = result['timing'].get('llm_call_count', 0)
        structured_failed = bool(result.get('sources_fallback_eligible'))
        error = answer if answer.startswith(GENERATION_ERROR_PREFIX) else None
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    return {
        'answer': answer,
        'answer_chars': len(answer),
        'cited_sources': cited_sources,
        'confidence': confidence,
        'llm_calls': llm_calls,
        'structured_failed': structured_failed,
        'seconds': round(time.time() - started_at, 1),
        'error': error[:300] if error else None,
        **score(item, answer, cited_sources),
    }


def describe(record):
    if record['error']:
        return 'error'
    if record['fact_recall'] is None:
        return 'abstained' if record['abstained'] else 'ANSWERED (unanswerable question)'
    return f'facts {record["fact_recall"]:.0%}, sources {record["source_recall"]:.0%}'


def result_label(model, reasoning_effort):
    """Name under which the results are recorded: the Ollama model, suffixed when a reasoning effort is set."""
    return model + REASONING_SUFFIX + reasoning_effort if reasoning_effort else model


def execute(todo, runs, model, server_info, chunks_by_id, reasoning_effort=None):
    """Run the pending questions, appending each result. Returns False when the backend looks down."""
    def build_record(item, pass_number):
        return {
            'model': model, 'question_id': item['id'], 'pass_number': pass_number,
            'category': item['category'], 'answerable': item['answerable'],
            **server_info, **run_once(item, chunks_by_id[item['id']]),
        }

    with mock.patch.object(settings, 'RAG_REASONING_EFFORT', reasoning_effort):
        return execute_runs(todo, runs, RESULTS_PATH, build_record, describe)


def model_stats(records):
    valid = [record for record in records if not record['error']]
    answerable = [record for record in valid if record['answerable']]
    unanswerable = [record for record in valid if not record['answerable']]
    p50, p90 = latency_percentiles([record['seconds'] for record in valid])
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
        'p50': p50,
        'p90': p90,
        'vram': min((record['vram_fraction'] for record in records if record.get('vram_fraction') is not None), default=None),
    }


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
    for question_id in dict.fromkeys(record['question_id'] for record in records):
        cells = [question_cell([record for record in records if record['model'] == model and record['question_id'] == question_id])
                 for model in models]
        print(f'{question_id:<12}' + ''.join(f'{cell:>22}' for cell in cells))


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
    parser.add_argument('--reasoning-effort', help='reasoning effort sent with the request, e.g. none (default: model default)')
    parser.add_argument('--keep-loaded', action='store_true', help='do not unload the model at the end')
    parser.add_argument('--report', action='store_true', help='print the comparison of the recorded results and exit')
    args = parser.parse_args()

    if args.report:
        print_report(load_scored_runs())
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
    label = result_label(args.model, args.reasoning_effort)
    if args.fresh:
        run_store.discard_model(RESULTS_PATH, label)
    runs = load_scored_runs()
    todo = list(run_store.pending_runs(label, questions, args.passes, runs,
                                      lambda previous: args.retry_errors and bool(previous['error'])))
    if not todo:
        print_report(runs)
        return 0

    try:
        chunks_by_id = load_contexts(questions, args.refresh_contexts)
    except (BackendUnavailable, requests.RequestException) as error:
        print(f'[SKIP] {error}')
        return 2
    exit_code = run_on_model(args.model, args.context_length, args.keep_loaded,
                            lambda server_info: execute(todo, runs, label, server_info, chunks_by_id, args.reasoning_effort))
    print_report(runs)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
