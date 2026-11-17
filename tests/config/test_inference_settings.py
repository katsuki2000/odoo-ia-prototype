"""Each case runs in a fresh interpreter because settings are read at import time."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = (
    "import dotenv, json; dotenv.load_dotenv = lambda *args, **kwargs: None\n"
    "from config import settings as s\n"
    "print(json.dumps({name: getattr(s, name) for name in ("
    "'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY', 'EMBEDDING_BASE_URL', 'EMBEDDING_MODEL')}))"
)


def load_settings(extra_env):
    environment = {key: value for key, value in os.environ.items() if key != 'OLLAMA_HOST'}
    environment.update(extra_env)
    result = subprocess.run([sys.executable, '-c', PROBE], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_there_is_no_implicit_server():
    values = load_settings({})
    assert values['LLM_BASE_URL'] == ''
    assert values['EMBEDDING_BASE_URL'] == ''


def test_ollama_host_drives_llm_and_embeddings():
    values = load_settings({'OLLAMA_HOST': 'https://llm.internal:11434'})
    assert values['LLM_BASE_URL'] == 'https://llm.internal:11434/v1'
    assert values['EMBEDDING_BASE_URL'] == 'https://llm.internal:11434/v1'
    assert values['LLM_API_KEY'] == 'ollama'


def test_models_are_constants_not_environment_settings():
    values = load_settings({'LLM_MODEL': 'from-env', 'OLLAMA_MODEL': 'from-env', 'EMBEDDING_MODEL': 'from-env'})
    assert values['LLM_MODEL'] == 'gemma4:26b'
    assert values['EMBEDDING_MODEL'] == 'bge-m3:latest'
