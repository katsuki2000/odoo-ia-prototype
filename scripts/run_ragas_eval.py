#!/usr/bin/env python3
"""
scripts/run_ragas_eval.py

Score the answers stored by scripts/run_rag_model_eval.py with two RAGAS metrics: faithfulness (share of the
statements of the answer supported by the passages) and answer relevancy. Both rest on a judge LLM, which must not be
one of the candidates (todo/protocole_evaluation.md); it must support tool calling, RAGAS asks it for structured output.
Only answerable questions are scored: refusals are measured by the abstention heuristic of the generation bench.
Each score is appended to captures/ragas_eval_<judge>.jsonl, so an interrupted run resumes where it stopped.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from openai import AsyncOpenAI
from ragas.embeddings.base import embedding_factory
from ragas.llms.base import llm_factory
from ragas.metrics.collections import AnswerRelevancy, Faithfulness

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import config.settings as settings
from evaluation import run_store
from evaluation.bench_common import mean, pct

ANSWERS_PATH = project_root / 'captures' / 'rag_model_eval.jsonl'
CONTEXTS_PATH = project_root / 'captures' / 'rag_eval_contexts.json'


def results_path(judge):
    return project_root / 'captures' / f'ragas_eval_{re.sub(r"[^A-Za-z0-9._-]+", "_", judge)}.jsonl'


def scorable_answers(runs):
    return [record for record in runs.values() if record['answerable'] and not record['error'] and record['answer'].strip()]


def pending_answers(answers, results, retry_errors):
    return [
        record for record in answers
        if (previous := results.get(run_store.run_key(record))) is None or (retry_errors and previous['error'])
    ]


def build_metrics(judge):
    llm_client = AsyncOpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY, default_headers=settings.LLM_EXTRA_HEADERS)
    embedding_client = AsyncOpenAI(base_url=settings.EMBEDDING_BASE_URL, api_key=settings.EMBEDDING_API_KEY,
                                   default_headers=settings.LLM_EXTRA_HEADERS)
    llm = llm_factory(judge, client=llm_client, temperature=0)
    embeddings = embedding_factory('openai', model=settings.EMBEDDING_MODEL, client=embedding_client)
    return Faithfulness(llm=llm), AnswerRelevancy(llm=llm, embeddings=embeddings)


async def score_answer(record, context, faithfulness, relevancy):
    question = context['question']
    passages = [chunk['document'] for chunk in context['chunks']]
    calls = {
        'faithfulness': faithfulness.ascore(user_input=question, response=record['answer'], retrieved_contexts=passages),
        'answer_relevancy': relevancy.ascore(user_input=question, response=record['answer']),
    }
    scores, errors = {}, []
    for name, call in calls.items():
        try:
            scores[name] = (await call).value
        except Exception as error:
            scores[name] = None
            errors.append(f'{name}: {type(error).__name__}: {error}'[:300])
    return {**scores, 'error': '; '.join(errors) or None}


async def score_all(judge, todo, contexts, path):
    faithfulness, relevancy = build_metrics(judge)
    for index, record in enumerate(todo, 1):
        result = await score_answer(record, contexts[record['question_id']], faithfulness, relevancy)
        run_store.append_run(path, {
            'model': record['model'], 'question_id': record['question_id'], 'pass_number': record['pass_number'],
            'judge': judge, **result,
        })
        print(f"[{index}/{len(todo)}] {record['model']} {record['question_id']} pass {record['pass_number']}"
              f" faithfulness={result['faithfulness']} relevancy={result['answer_relevancy']}")


def summarise(results):
    """Per answering model: scored answers, mean faithfulness and mean answer relevancy."""
    summary = {}
    for model in sorted({record['model'] for record in results.values()}):
        records = [record for record in results.values() if record['model'] == model and not record['error']]
        summary[model] = (
            len(records),
            mean([record['faithfulness'] for record in records]),
            mean([record['answer_relevancy'] for record in records]),
        )
    return summary


def print_report(results, judge):
    errors = sum(1 for record in results.values() if record['error'])
    print(f'Judge: {judge}; answers scored without error are averaged, {errors} with error left out.')
    print(f"{'model':<28}{'scored':>8}{'faithfulness':>14}{'relevancy':>11}")
    for model, (count, faithfulness, relevancy) in summarise(results).items():
        print(f'{model:<28}{count:>8}{pct(faithfulness):>14}{pct(relevancy):>11}')


def main():
    parser = argparse.ArgumentParser(description='Score the stored documentary answers with RAGAS faithfulness and answer relevancy.')
    parser.add_argument('--judge', required=True, help='Ollama model that judges, distinct from every candidate')
    parser.add_argument('--retry-errors', action='store_true', help='score again the answers recorded with an error')
    parser.add_argument('--report', action='store_true', help='print the recorded scores without scoring')
    args = parser.parse_args()

    path = results_path(args.judge)
    results = run_store.load_runs(path)
    if args.report:
        print_report(results, args.judge)
        return 0
    answers = scorable_answers(run_store.load_runs(ANSWERS_PATH))
    if args.judge in {record['model'] for record in answers}:
        print(f'[ERROR] {args.judge} is one of the candidates: the judge must be a different model.')
        return 1
    todo = pending_answers(answers, results, args.retry_errors)
    if todo:
        contexts = json.loads(CONTEXTS_PATH.read_text(encoding='utf-8'))
        asyncio.run(score_all(args.judge, todo, contexts, path))
    print_report(run_store.load_runs(path), args.judge)
    return 0


if __name__ == '__main__':
    sys.exit(main())
