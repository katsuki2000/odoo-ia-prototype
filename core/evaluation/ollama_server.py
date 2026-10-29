"""Ollama server control shared by the model comparison benches: one chat model loaded at a time."""

import contextlib
from unittest import mock

import requests

import config.settings as settings
from core.llm import llm_client
from core.evaluation.preflight import BackendUnavailable

SERVER_TIMEOUT_SECONDS = 900


def server_call(method, path, payload=None):
    url = f'{settings.LLM_BASE_URL.removesuffix("/v1")}{path}'
    response = requests.request(method, url, json=payload, timeout=SERVER_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json() if response.content else {}


def loaded_models():
    return {entry['name']: entry for entry in server_call('GET', '/api/ps').get('models', [])}


def set_keep_alive(model, keep_alive):
    server_call('POST', '/api/generate', {'model': model, 'keep_alive': keep_alive, 'stream': False})


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
        for module in (settings, llm_client):
            stack.enter_context(mock.patch.object(module, 'LLM_MODEL', model))
            stack.enter_context(mock.patch.object(module, 'LLM_NO_THINK_MARKER', marker))
        yield
