"""Environment and instance configuration."""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from config.odoo_conf import resolve_addon_paths, resolve_database, resolve_odoo_url

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env')
# The environment (.env) supplies only what varies per machine or deployment: secrets, addresses (LLM server,
# Odoo instance, API bind) and locations of external Odoo installs; every other setting is a constant defined here.
# Kaggle is a temporary dev host: delete its entry (and the KAGGLE_* variables) to drop it.
LLM_TARGETS = {
    'aws': {'prefix': 'AWS', 'headers': {}},
    'kaggle': {'prefix': 'KAGGLE', 'headers': {'ngrok-skip-browser-warning': '1'}},
}
LLM_TARGET = os.getenv('LLM_TARGET', 'aws').strip().lower()
if LLM_TARGET not in LLM_TARGETS:
    raise ValueError(f'LLM_TARGET must be one of {sorted(LLM_TARGETS)}, got {LLM_TARGET!r}.')
LLM_EXTRA_HEADERS = LLM_TARGETS[LLM_TARGET]['headers']
LLM_TARGET_PREFIX = LLM_TARGETS[LLM_TARGET]['prefix']


def _target_setting(name, default=''):
    return os.getenv(f'{LLM_TARGET_PREFIX}_{name}') or default


OLLAMA_HOST = _target_setting('OLLAMA_HOST')
_ollamaUrl = f'{OLLAMA_HOST}/v1' if OLLAMA_HOST else ''
LLM_BASE_URL = _target_setting('LLM_BASE_URL', _ollamaUrl)
LLM_MODEL = 'qwen3:14b'
LLM_API_KEY = _target_setting('LLM_API_KEY', 'ollama')
LLM_NO_THINK_MARKER = '/no_think' if LLM_MODEL.lower().startswith('qwen3') else ''
LLM_REQUEST_TIMEOUT_SECONDS = 90.0
LLM_INTERACTIVE_MAX_RETRIES = 1
EMBEDDING_BASE_URL = _target_setting('EMBEDDING_BASE_URL', _ollamaUrl)
EMBEDDING_MODEL = 'bge-m3:latest'
EMBEDDING_API_KEY = _target_setting('EMBEDDING_API_KEY', 'ollama')


def require_inference_server(url):
    if not url:
        raise ValueError(f'No inference server configured: set {LLM_TARGET_PREFIX}_OLLAMA_HOST in .env.')
    return url


CHROMA_PATH = str(_ROOT / 'document_rag' / 'vectorstore' / 'chroma_db')
DOCS_COLLECTION_NAME = 'odoo_docs'
ANSWER_VERIFIER_MODE = 'report'

# Source routing confidence is an operator policy, not a calibrated probability.
SOURCE_SELECTION_MIN_CONFIDENCE = 0.75
if not 0.0 <= SOURCE_SELECTION_MIN_CONFIDENCE <= 1.0:
    raise ValueError('SOURCE_SELECTION_MIN_CONFIDENCE must be between 0 and 1.')
SENSITIVE_EVIDENCE_GROUP_XMLIDS = frozenset()

_explicit_core = os.getenv('CORE_ADDONS_PATH')
_default_odoo_root = Path(_explicit_core).parent if _explicit_core else _ROOT.parent / 'odoo-17.0'
_default_odoo_conf = _default_odoo_root / 'odoo.conf'
_conf_for_addon_paths = (os.getenv('ODOO_CONF_PATH') or os.getenv('EVAL_ODOO_CONF') or os.getenv('ODOO_RC')
                         or (str(_default_odoo_conf) if _default_odoo_conf.is_file() else None))
_ADDON_PATHS = resolve_addon_paths(_conf_for_addon_paths, os.environ, _default_odoo_root, _ROOT)
CORE_ADDONS_PATH = _ADDON_PATHS.core
CUSTOM_ADDONS_PATH = _ADDON_PATHS.custom[0]
CUSTOM_ADDONS_PATHS = _ADDON_PATHS.custom
logging.getLogger(__name__).info(
    'Addon paths (source): core=%s (%s), framework=%s (%s), custom=%s (%s)',
    _ADDON_PATHS.core, _ADDON_PATHS.sources['CORE_ADDONS_PATH'],
    _ADDON_PATHS.framework, _ADDON_PATHS.sources['CORE_FRAMEWORK_ADDONS_PATH'],
    list(_ADDON_PATHS.custom), _ADDON_PATHS.sources['CUSTOM_ADDONS_PATH'])
_ODOO_ROOT = Path(CORE_ADDONS_PATH).parent
_ODOO_VENV_PYTHON = _ODOO_ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
_ODOO_DEFAULT_CONF = _ODOO_ROOT / 'odoo.conf'
EVAL_ODOO_BIN = os.getenv('EVAL_ODOO_BIN') or str(_ODOO_ROOT / 'odoo-bin')
EVAL_ODOO_PYTHON = os.getenv('EVAL_ODOO_PYTHON') or (str(_ODOO_VENV_PYTHON) if _ODOO_VENV_PYTHON.is_file() else sys.executable)
EVAL_ODOO_CONF = os.getenv('EVAL_ODOO_CONF') or (str(_ODOO_DEFAULT_CONF) if _ODOO_DEFAULT_CONF.is_file() else None)
ODOO_CONF_PATH = os.getenv('ODOO_CONF_PATH') or os.getenv('EVAL_ODOO_CONF') or os.getenv('ODOO_RC') or EVAL_ODOO_CONF
ODOO_DB_DEFAULT, _odoo_db_source = resolve_database(ODOO_CONF_PATH, os.environ)
ODOO_URL_DEFAULT, _odoo_url_source = resolve_odoo_url(ODOO_CONF_PATH, os.environ)
logging.getLogger(__name__).info('Odoo connection defaults (source): url=%s (%s), db=%s (%s)',
    ODOO_URL_DEFAULT, _odoo_url_source, ODOO_DB_DEFAULT, _odoo_db_source)
EVAL_DB_PREFIX = 'eval_'
EVAL_INSTANCE_ADMIN_PASSWORD = os.getenv('EVAL_INSTANCE_ADMIN_PASSWORD', 'admin')
EVAL_INSTANCES_DIR = str(_ROOT / 'captures' / 'eval_instances')
EVAL_OCA_ADDONS_PATH = os.getenv('EVAL_OCA_ADDONS_PATH') or None
GRAPH_CACHE_PATH = os.getenv('GRAPH_CACHE_PATH') or str(_ROOT / 'active_graph.json')
GRAPH_TRANSLATION_LANGUAGES = ('en_US', 'fr_FR')
SEMANTIC_INDEX_CACHE_DIR = str(_ROOT / 'active_semantic_index')
RAG_DOCS_PATH = str(_ROOT / 'document_rag' / 'documents')
RAG_CHUNK_SIZE = 512
RAG_CHUNK_OVERLAP = 50
DOCUMENT_MAX_TOKENS = 2048
CORE_FRAMEWORK_ADDONS_PATH = _ADDON_PATHS.framework
SOURCE_LINK_ROOTS = tuple(str(path) for path in (CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, *CUSTOM_ADDONS_PATHS) if path)
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
LATENCY_BUDGET_P90_SECONDS = 12.0
ORM_RUNTIME_MAX_ROWS = 100
ORM_NAME_SEARCH_LIMIT = 20
SEMGREP_TIMEOUT_SECONDS = 120
EMBEDDING_TIMEOUT = 30.0
RESOLVER_SEMANTIC_RETRIEVAL_ENABLED = True
# Bump to invalidate every persisted resolver semantic index (part of the provider identity).
RESOLVER_SEMANTIC_EMBEDDING_REVISION = ''
MASSIVE_EXTRACTION_REFUSAL_MSG = 'La demande dépasse le périmètre d\'analyse autorisé.'
PROMPT_INJECTION_REFUSAL_MSG = 'Demande non autorisée : les consignes système et politiques de sécurité ne peuvent pas être altérées ou divulguées.'
