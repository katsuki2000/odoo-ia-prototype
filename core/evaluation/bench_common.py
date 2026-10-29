"""Helpers shared by the model comparison benches: answer matching, statistics, run loop, model cycle."""

import math
import re
import statistics
import unicodedata

import requests

from core.evaluation import run_store
from core.evaluation.ollama_server import model_override, prepare_server, set_keep_alive
from core.evaluation.preflight import BackendUnavailable, require_backends

MAX_CONSECUTIVE_ERRORS = 3


def _fold_accents(text):
    """Strip diacritics (NFD, combining marks removed)."""
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def normalize(text):
    """Case, accent, blank and markdown-emphasis insensitive form used to find a fact in an answer.
    Line breaks are kept: they end a number, so 'HEAD~1' then a line '3. ...' is not read as 'HEAD~13'."""
    return re.sub(r'[^\S\n]+|[*`]', '', _fold_accents(text.casefold()).replace('’', "'"))


def contains_fact(folded_answer, fact):
    """A normalized fact occurs in the text, even wrapped over lines (OCR, hard-wrapped sources); a number is never
    matched inside a longer one (4 heures vs 24 heures), a line break ending it."""
    needle = normalize(fact)
    before = r'(?<!\d)' if needle[0].isdigit() else ''
    after = r'(?!\d)' if needle[-1].isdigit() else ''
    return re.search(before + '\n?'.join(map(re.escape, needle)) + after, folded_answer) is not None


def mean(values):
    return statistics.mean(values) if values else None


def latency_percentiles(seconds):
    """(p50, p90) of the durations, (None, None) without any."""
    ordered = sorted(seconds)
    if not ordered:
        return None, None
    return statistics.median(ordered), ordered[math.ceil(0.9 * len(ordered)) - 1]


def pct(value):
    return 'n/a' if value is None else f'{value:.0%}'


def seconds_text(value):
    return 'n/a' if value is None else f'{value:.0f}'


def require_context_length(server_info, expected):
    actual = server_info.get('context_length')
    if actual != expected:
        raise BackendUnavailable(
            f'Expected Ollama context length {expected}, got {actual!r}; '
            'set OLLAMA_CONTEXT_LENGTH consistently before comparing models.'
        )


def rescore_runs(runs, questions, score_record):
    """Recompute the scores of the recorded runs without error with the current question set."""
    questions_by_id = {item['id']: item for item in questions}
    for record in runs.values():
        item = questions_by_id.get(record['question_id'])
        if item and not record['error']:
            record.update(score_record(item, record))
    return runs


def execute_runs(todo, runs, results_path, build_record, describe):
    """Run the pending (question, pass) pairs, appending each record. Returns False when the backend looks down."""
    consecutive_errors = 0
    for number, (item, pass_number) in enumerate(todo, 1):
        record = build_record(item, pass_number)
        run_store.append_run(results_path, record)
        runs[run_store.run_key(record)] = record
        print(f'[{number}/{len(todo)}] {item["id"]} pass {pass_number}: {describe(record)} ({record["seconds"]}s)', flush=True)
        consecutive_errors = consecutive_errors + 1 if record['error'] else 0
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            print(f'{consecutive_errors} consecutive errors: the backend looks down. '
                  'Restore it, then rerun with --retry-errors.')
            return False
    return True


def run_on_model(model, context_length, keep_loaded, execute, probes=None):
    """Load the model, check its context length, run `execute(serverInfo)` with it as the chat model, unload it.

    Returns the exit code: 0 finished, 2 model not loadable, 3 backend down or run interrupted.
    """
    try:
        server_info = prepare_server(model)
    except (BackendUnavailable, requests.RequestException) as error:
        print(f'[SKIP] {error}')
        return 2
    print(f'{model} loaded: {server_info}')
    finished = False
    try:
        require_context_length(server_info, context_length)
        with model_override(model):
            require_backends(probes)
            finished = execute(server_info)
    except BackendUnavailable as error:
        print(f'[SKIP] Backend unavailable, no run started: {error}')
    finally:
        if not keep_loaded:
            set_keep_alive(model, 0)
    return 0 if finished else 3
