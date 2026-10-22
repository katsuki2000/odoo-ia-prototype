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
    "'LLM_TARGET', 'LOCAL_LLM_BASE_URL', 'LOCAL_LLM_MODEL', 'LOCAL_LLM_API_KEY', "
    "'LOCAL_EMBEDDING_BASE_URL', 'LOCAL_EMBEDDING_MODEL', 'LLM_EXTRA_HEADERS')}))"
)
TARGET_VARIABLES = ('LLM_TARGET', 'OLLAMA_HOST', 'OLLAMA_MODEL', 'LOCAL_LLM_BASE_URL', 'LOCAL_LLM_MODEL',
                    'LOCAL_LLM_API_KEY', 'LOCAL_EMBEDDING_BASE_URL', 'LOCAL_EMBEDDING_MODEL')


def run_probe(extraEnv):
    environment = {key: value for key, value in os.environ.items()
                   if key not in TARGET_VARIABLES and not key.startswith(('AWS_', 'KAGGLE_'))}
    environment.update(extraEnv)
    return subprocess.run([sys.executable, '-c', PROBE], cwd=ROOT, env=environment,
                          capture_output=True, text=True, timeout=60)


def load_settings(extraEnv):
    result = run_probe(extraEnv)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_default_target_is_aws_on_the_local_instance():
    values = load_settings({})
    assert values['LLM_TARGET'] == 'aws'
    assert values['LOCAL_LLM_BASE_URL'] == 'http://localhost:11434/v1'
    assert values['LOCAL_EMBEDDING_BASE_URL'] == 'http://localhost:11434/v1'
    assert values['LLM_EXTRA_HEADERS'] == {}


def test_aws_variables_drive_llm_and_embeddings():
    values = load_settings({'AWS_OLLAMA_HOST': 'https://llm.internal:11434', 'AWS_OLLAMA_MODEL': 'qwen3:14b'})
    assert values['LOCAL_LLM_BASE_URL'] == 'https://llm.internal:11434/v1'
    assert values['LOCAL_EMBEDDING_BASE_URL'] == 'https://llm.internal:11434/v1'
    assert values['LOCAL_LLM_MODEL'] == 'qwen3:14b'


def test_unprefixed_variables_remain_a_fallback():
    values = load_settings({'OLLAMA_HOST': 'http://generic:11434', 'LOCAL_LLM_MODEL': 'generic-model'})
    assert values['LOCAL_LLM_BASE_URL'] == 'http://generic:11434/v1'
    assert values['LOCAL_LLM_MODEL'] == 'generic-model'


def test_prefixed_variable_wins_over_unprefixed():
    values = load_settings({'AWS_LLM_MODEL': 'from-aws', 'LOCAL_LLM_MODEL': 'generic-model'})
    assert values['LOCAL_LLM_MODEL'] == 'from-aws'


def test_kaggle_target_uses_its_own_host_and_header():
    values = load_settings({'LLM_TARGET': 'kaggle', 'KAGGLE_OLLAMA_HOST': 'https://tunnel.example',
                            'AWS_OLLAMA_HOST': 'https://llm.internal:11434'})
    assert values['LOCAL_LLM_BASE_URL'] == 'https://tunnel.example/v1'
    assert values['LLM_EXTRA_HEADERS'] == {'ngrok-skip-browser-warning': '1'}


def test_unknown_target_is_rejected_with_the_valid_choices():
    result = run_probe({'LLM_TARGET': 'gcp'})
    assert result.returncode != 0
    assert 'LLM_TARGET must be one of' in result.stderr
