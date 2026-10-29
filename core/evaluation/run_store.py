"""Append-only JSONL store of benchmark runs keyed by (model, question, pass): an interrupted bench resumes."""

import json


def run_key(record):
    return record['model'], record['question_id'], record['pass_number']


def load_runs(path):
    if not path.exists():
        return {}
    with open(path, encoding='utf-8') as file:
        return {run_key(record): record for record in map(json.loads, filter(str.strip, file))}


def append_run(path, record):
    path.parent.mkdir(exist_ok=True)
    with open(path, 'a', encoding='utf-8') as file:
        file.write(json.dumps(record, ensure_ascii=False) + '\n')


def discard_model(path, model):
    kept = [record for key, record in load_runs(path).items() if key[0] != model]
    with open(path, 'w', encoding='utf-8') as file:
        file.writelines(json.dumps(record, ensure_ascii=False) + '\n' for record in kept)


def pending_runs(model, questions, passes, runs, is_retryable):
    for pass_number in range(1, passes + 1):
        for item in questions:
            previous = runs.get((model, item['id'], pass_number))
            if previous is None or is_retryable(previous):
                yield item, pass_number
