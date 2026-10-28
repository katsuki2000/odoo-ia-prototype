"""Environment and instance configuration."""

import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env')
# The environment (.env) supplies only what varies per machine or deployment: secrets, addresses (LLM server,
# Odoo instance, API bind) and locations of external Odoo installs; every other setting is a constant defined here.
# The default target reads unprefixed variables (OLLAMA_HOST, ...); kaggle, a temporary dev host, reads KAGGLE_*:
# delete its entry to drop it.
LLM_TARGETS = {
    'aws': {'prefix': '', 'headers': {}},
    'kaggle': {'prefix': 'KAGGLE_', 'headers': {'ngrok-skip-browser-warning': '1'}},
}
LLM_TARGET = os.getenv('LLM_TARGET', 'aws').strip().lower()
if LLM_TARGET not in LLM_TARGETS:
    raise ValueError(f'LLM_TARGET must be one of {sorted(LLM_TARGETS)}, got {LLM_TARGET!r}.')
LLM_EXTRA_HEADERS = LLM_TARGETS[LLM_TARGET]['headers']
LLM_TARGET_PREFIX = LLM_TARGETS[LLM_TARGET]['prefix']


def _target_setting(name, default=''):
    return os.getenv(f'{LLM_TARGET_PREFIX}{name}') or default


OLLAMA_HOST = _target_setting('OLLAMA_HOST')
_ollamaUrl = f'{OLLAMA_HOST}/v1' if OLLAMA_HOST else ''
LLM_BASE_URL = _target_setting('LLM_BASE_URL', _ollamaUrl)
LLM_MODEL = 'qwen3:14b'
LLM_API_KEY = _target_setting('LLM_API_KEY', 'ollama')
LLM_NO_THINK_MARKER = '/no_think' if LLM_MODEL.lower().startswith('qwen3') else ''
LLM_REQUEST_TIMEOUT_SECONDS = 90.0
EMBEDDING_BASE_URL = _target_setting('EMBEDDING_BASE_URL', _ollamaUrl)
EMBEDDING_MODEL = 'bge-m3:latest'
EMBEDDING_API_KEY = _target_setting('EMBEDDING_API_KEY', 'ollama')


def require_inference_server(url):
    if not url:
        raise ValueError(f'No inference server configured: set {LLM_TARGET_PREFIX}OLLAMA_HOST in .env.')
    return url


CHROMA_PATH = str(_ROOT / 'document_rag' / 'vectorstore' / 'chroma_db')
DOCS_COLLECTION_NAME = 'odoo_docs'
ANSWER_VERIFIER_MODE = 'report'

# Source routing confidence is an operator policy, not a calibrated probability.
SOURCE_SELECTION_MIN_CONFIDENCE = 0.75
if not 0.0 <= SOURCE_SELECTION_MIN_CONFIDENCE <= 1.0:
    raise ValueError('SOURCE_SELECTION_MIN_CONFIDENCE must be between 0 and 1.')

CORE_ADDONS_PATH = os.getenv('CORE_ADDONS_PATH') or str(_ROOT.parent / 'odoo-17.0' / 'addons')
CUSTOM_ADDONS_PATH = os.getenv('CUSTOM_ADDONS_PATH') or str(_ROOT / 'odoo_addons')
ODOO_URL_DEFAULT = 'http://localhost:8069'
ODOO_DB_DEFAULT = 'odoo-dev'
RAG_DOCS_PATH = str(_ROOT / 'document_rag' / 'documents')
RAG_CHUNK_SIZE = 512
RAG_CHUNK_OVERLAP = 50
DOCUMENT_MAX_TOKENS = 2048
VECTOR_SIMILARITY_FLOOR = 0.20
RAG_VECTOR_WEIGHT = 0.7
RAG_BM25_WEIGHT = 0.3
RAG_RELEVANCE_THRESHOLD = 0.01
RAG_TOP_K = 10
API_HOST = os.getenv('API_HOST', '127.0.0.1')


def parse_cors_origins(raw: str) -> list[str]:
    origins = [origin.strip().rstrip('/') for origin in raw.split(',')]
    return [origin for origin in origins if origin and origin != '*']


CORS_ALLOWED_ORIGINS = parse_cors_origins(os.getenv('CORS_ALLOWED_ORIGINS', ''))
API_PORT = int(os.getenv('API_PORT', '8000'))
ASK_JOB_WORKERS = 2
ASK_JOB_MAX_PENDING = 20
ASK_JOB_TTL_SECONDS = 1800
ORM_RUNTIME_MAX_ROWS = 100
ORM_NAME_SEARCH_LIMIT = 20
EMBEDDING_TIMEOUT = 30.0
PROMPT_INJECTION_REFUSAL_MSG = 'Demande non autorisée : les consignes système et politiques de sécurité ne peuvent pas être altérées ou divulguées.'
