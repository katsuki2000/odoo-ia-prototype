from pathlib import Path

path = Path('scripts/run_rag_model_eval.py')
text = path.read_text(encoding='utf-8')


def swap(old, new):
    global text
    assert text.count(old) == 1, old[:60]
    text = text.replace(old, new)


swap('''import argparse
import json
import math
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path
''', '''import argparse
import json
import sys
import time
from pathlib import Path
''')
swap('''from core.evaluation import run_store as runStore
from core.evaluation.ollama_server import model_override, prepare_server, set_keep_alive
from core.evaluation.preflight import BackendUnavailable, require_backends
''', '''from core.evaluation import run_store as runStore
from core.evaluation.bench_common import (
    contains_fact, execute_runs, latency_percentiles, mean, normalize, pct, rescore_runs, run_on_model, seconds_text,
)
from core.evaluation.preflight import BackendUnavailable
''')
swap("MAX_CONSECUTIVE_ERRORS = 3\n", "")
swap('''def _fold_accents(text):
    """Strip diacritics (NFD, combining marks removed)."""
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def normalize(text):
    """Case, accent, whitespace and markdown-emphasis insensitive form used to find a fact in an answer."""
    return re.sub(r'[\\s*`]+', '', _fold_accents(text.casefold()).replace('\u2019', "'"))


''', '')
swap('''def contains_fact(foldedAnswer, fact):
    """A normalized fact occurs in the answer; a number is never matched inside a longer one (4 heures vs 24 heures)."""
    needle = re.escape(normalize(fact))
    before = r'(?<!\\d)' if needle[0].isdigit() else ''
    after = r'(?!\\d)' if needle[-1].isdigit() else ''
    return re.search(before + needle + after, foldedAnswer) is not None


''', '')
swap('''    runs = runStore.load_runs(RESULTS_PATH)
    questionsById = {item['id']: item for item in load_questions(None)}
    for record in runs.values():
        item = questionsById.get(record['question_id'])
        if item and not record['error']:
            record.update(score(item, record['answer'], record['cited_sources']))
    return runs


def require_context_length(serverInfo, expected):
    actual = serverInfo.get('context_length')
    if actual != expected:
        raise BackendUnavailable(
            f'Expected Ollama context length {expected}, got {actual!r}; '
            'set OLLAMA_CONTEXT_LENGTH consistently before comparing models.'
        )
''', '''    return rescore_runs(runStore.load_runs(RESULTS_PATH), load_questions(None),
                        lambda item, record: score(item, record['answer'], record['cited_sources']))
''')
swap('''    """Run the pending questions, appending each result. Returns False when the backend looks down."""
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
''', '''    """Run the pending questions, appending each result. Returns False when the backend looks down."""
    def build_record(item, passNumber):
        return {
            'model': model, 'question_id': item['id'], 'pass_number': passNumber,
            'category': item['category'], 'answerable': item['answerable'],
            **serverInfo, **run_once(item, chunksById[item['id']]),
        }

    return execute_runs(todo, runs, RESULTS_PATH, build_record, describe)
''')
swap('''    seconds = sorted(record['seconds'] for record in valid)
    return {''', '''    p50, p90 = latency_percentiles([record['seconds'] for record in valid])
    return {''')
swap('''        'p50': statistics.median(seconds) if seconds else None,
        'p90': seconds[math.ceil(0.9 * len(seconds)) - 1] if seconds else None,
''', '''        'p50': p50,
        'p90': p90,
''')
swap('''def pct(value):
    return 'n/a' if value is None else f'{value:.0%}'


def seconds_text(value):
    return 'n/a' if value is None else f'{value:.0f}'


''', '')
swap('''    try:
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
''', '''    try:
        chunksById = load_contexts(questions, args.refresh_contexts)
    except (BackendUnavailable, requests.RequestException) as error:
        print(f'[SKIP] {error}')
        return 2
    exitCode = run_on_model(args.model, args.context_length, args.keep_loaded,
                            lambda serverInfo: execute(todo, runs, args.model, serverInfo, chunksById))
    print_report(runs)
    return exitCode
''')
path.write_text(text, encoding='utf-8')
print('ok')
