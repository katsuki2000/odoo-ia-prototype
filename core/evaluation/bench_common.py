"""Helpers shared by the model comparison benches: answer matching, statistics, run loop, model cycle."""

import math
import re
import statistics
import unicodedata

import requests

from core.evaluation import run_store as runStore
from core.evaluation.ollama_server import model_override, prepare_server, set_keep_alive
from core.evaluation.preflight import BackendUnavailable, require_backends

MAX_CONSECUTIVE_ERRORS = 3


def _fold_accents(text):
    """Strip diacritics (NFD, combining marks removed)."""
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def normalize(text):
    """Case, accent, whitespace and markdown-emphasis insensitive form used to find a fact in an answer."""
    return re.sub(r'[\s*`]+', '', _fold_accents(text.casefold()).replace('’', "'"))


def contains_fact(foldedAnswer, fact):
    """A normalized fact occurs in the answer; a number is never matched inside a longer one (4 heures vs 24 heures)."""
    needle = re.escape(normalize(fact))
    before = r'(?<!\d)' if needle[0].isdigit() else ''
    after = r'(?!\d)' if needle[-1].isdigit() else ''
    return re.search(before + needle + after, foldedAnswer) is not None


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


def require_context_length(serverInfo, expected):
    actual = serverInfo.get('context_length')
    if actual != expected:
        raise BackendUnavailable(
            f'Expected Ollama context length {expected}, got {actual!r}; '
            'set OLLAMA_CONTEXT_LENGTH consistently before comparing models.'
        )


def rescore_runs(runs, questions, scoreRecord):
    """Recompute the scores of the recorded runs without error with the current question set."""
    questionsById = {item['id']: item for item in questions}
    for record in runs.values():
        item = questionsById.get(record['question_id'])
        if item and not record['error']:
            record.update(scoreRecord(item, record))
    return runs


def execute_runs(todo, runs, resultsPath, buildRecord, describe):
    """Run the pending (question, pass) pairs, appending each record. Returns False when the backend looks down."""
    consecutiveErrors = 0
    for number, (item, passNumber) in enumerate(todo, 1):
        record = buildRecord(item, passNumber)
        runStore.append_run(resultsPath, record)
        runs[runStore.run_key(record)] = record
        print(f'[{number}/{len(todo)}] {item["id"]} pass {passNumber}: {describe(record)} ({record["seconds"]}s)', flush=True)
        consecutiveErrors = consecutiveErrors + 1 if record['error'] else 0
        if consecutiveErrors >= MAX_CONSECUTIVE_ERRORS:
            print(f'{consecutiveErrors} consecutive errors: the backend looks down. '
                  'Restore it, then rerun with --retry-errors.')
            return False
    return True


def run_on_model(model, contextLength, keepLoaded, execute, probes=None):
    """Load the model, check its context length, run `execute(serverInfo)` with it as the chat model, unload it.

    Returns the exit code: 0 finished, 2 model not loadable, 3 backend down or run interrupted.
    """
    try:
        serverInfo = prepare_server(model)
    except (BackendUnavailable, requests.RequestException) as error:
        print(f'[SKIP] {error}')
        return 2
    print(f'{model} loaded: {serverInfo}')
    finished = False
    try:
        require_context_length(serverInfo, contextLength)
        with model_override(model):
            require_backends(probes)
            finished = execute(serverInfo)
    except BackendUnavailable as error:
        print(f'[SKIP] Backend unavailable, no run started: {error}')
    finally:
        if not keepLoaded:
            set_keep_alive(model, 0)
    return 0 if finished else 3
