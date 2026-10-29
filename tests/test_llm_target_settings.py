"""Each case runs in a fresh interpreter because settings are read at import time."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = (
    "import dotenv, json; dotenv.load_dotenv = lambda *args, **kwargs: None\n"
    "from config import settings as s\n"
    "print(json.dumps({name: getattr(s, name) for name in ("
    "'LLM_TARGET', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY', "
    "'EMBEDDING_BASE_URL', 'EMBEDDING_MODEL', 'LLM_EXTRA_HEADERS')}))"
)
TARGET_VARIABLES = ('LLM_TARGET', 'OLLAMA_HOST', 'LLM_BASE_URL', 'LLM_API_KEY', 'EMBEDDING_BASE_URL', 'EMBEDDING_API_KEY')


def run_probe(extra_env):
    environment = {key: value for key, value in os.environ.items()
                   if key not in TARGET_VARIABLES and not key.startswith('KAGGLE_')}
    environment.update(extra_env)
    return subprocess.run([sys.executable, '-c', PROBE], cwd=ROOT, env=environment,
                          capture_output=True, text=True, timeout=60)


def load_settings(extra_env):
    result = run_probe(extra_env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_default_target_is_aws_and_has_no_implicit_server():
    values = load_settings({})
    assert values['LLM_TARGET'] == 'aws'
    assert values['LLM_BASE_URL'] == ''
    assert values['EMBEDDING_BASE_URL'] == ''
    assert values['LLM_EXTRA_HEADERS'] == {}


def test_ollama_host_drives_llm_and_embeddings():
    values = load_settings({'OLLAMA_HOST': 'https://llm.internal:11434'})
    assert values['LLM_BASE_URL'] == 'https://llm.internal:11434/v1'
    assert values['EMBEDDING_BASE_URL'] == 'https://llm.internal:11434/v1'
    assert values['LLM_MODEL'] == 'qwen3:14b'


def test_default_target_ignores_kaggle_variables():
    values = load_settings({'KAGGLE_OLLAMA_HOST': 'https://tunnel.example'})
    assert values['LLM_BASE_URL'] == ''


def test_models_are_constants_not_environment_settings():
    values = load_settings({'LLM_MODEL': 'from-env', 'OLLAMA_MODEL': 'from-env', 'EMBEDDING_MODEL': 'from-env'})
    assert values['LLM_MODEL'] == 'qwen3:14b'
    assert values['EMBEDDING_MODEL'] == 'bge-m3:latest'


def test_kaggle_target_uses_its_own_host_and_header():
    values = load_settings({'LLM_TARGET': 'kaggle', 'KAGGLE_OLLAMA_HOST': 'https://tunnel.example',
                            'OLLAMA_HOST': 'https://llm.internal:11434'})
    assert values['LLM_BASE_URL'] == 'https://tunnel.example/v1'
    assert values['LLM_EXTRA_HEADERS'] == {'ngrok-skip-browser-warning': '1'}


def test_unknown_target_is_rejected_with_the_valid_choices():
    result = run_probe({'LLM_TARGET': 'gcp'})
    assert result.returncode != 0
    assert 'LLM_TARGET must be one of' in result.stderr
