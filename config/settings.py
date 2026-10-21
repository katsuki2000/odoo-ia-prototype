"""Environment and instance configuration."""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from config.odoo_conf import resolve_addon_paths, resolve_database, resolve_odoo_url

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env')
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'local')
LOCAL_ONLY = os.getenv('LOCAL_ONLY', 'true').lower() in ('true', '1', 'yes')
LOCAL_ALLOWED_HOSTS = frozenset(host.strip().lower() for host in os.getenv(
    'LOCAL_ALLOWED_HOSTS', 'localhost,127.0.0.1,::1').split(',') if host.strip())
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'gpt-oss:20b')
LOCAL_LLM_BASE_URL = os.getenv('LOCAL_LLM_BASE_URL', f'{OLLAMA_HOST}/v1')
LOCAL_LLM_MODEL = os.getenv('LOCAL_LLM_MODEL', OLLAMA_MODEL)
LOCAL_LLM_API_KEY = os.getenv('LOCAL_LLM_API_KEY', 'ollama')
LLM_NO_THINK_MARKER = os.getenv('LLM_NO_THINK_MARKER', '/no_think' if LOCAL_LLM_MODEL.lower().startswith('qwen3') else '')
DEFAULT_EMBEDDING_BACKEND = 'local_server'
EMBEDDING_BACKEND = os.getenv('EMBEDDING_BACKEND', DEFAULT_EMBEDDING_BACKEND).lower()
EMBEDDING_MODEL_NAME = os.getenv('EMBEDDING_MODEL', 'BAAI/bge-m3')
LOCAL_EMBEDDING_BASE_URL = os.getenv('LOCAL_EMBEDDING_BASE_URL', f'{OLLAMA_HOST}/v1')
LOCAL_EMBEDDING_MODEL = os.getenv('LOCAL_EMBEDDING_MODEL', 'bge-m3:latest')
LOCAL_EMBEDDING_API_KEY = os.getenv('LOCAL_EMBEDDING_API_KEY', 'ollama')
CI_MAX_HOPS = int(os.getenv('CI_MAX_HOPS', '15'))
CHROMA_PATH = os.getenv('CHROMA_PATH') or str(_ROOT / 'document_rag' / 'vectorstore' / 'chroma_db')
DOCS_COLLECTION_NAME = 'odoo_docs'
ANSWER_VERIFIER_MODE = os.getenv('ANSWER_VERIFIER_MODE', 'report')

# Source routing confidence is an operator policy, not a calibrated probability.
SOURCE_SELECTION_MIN_CONFIDENCE = float(os.getenv('SOURCE_SELECTION_MIN_CONFIDENCE', '0.75'))
if not 0.0 <= SOURCE_SELECTION_MIN_CONFIDENCE <= 1.0:
    raise ValueError('SOURCE_SELECTION_MIN_CONFIDENCE must be between 0 and 1.')
SENSITIVE_EVIDENCE_GROUP_XMLIDS = frozenset(
    value.strip() for value in os.getenv('SENSITIVE_EVIDENCE_GROUP_XMLIDS', '').split(',')
    if value.strip() and '.' in value and all(part for part in value.strip().split('.')))

_explicit_core = os.getenv('CORE_ADDONS_PATH')
_default_odoo_root = Path(_explicit_core).parent if _explicit_core else _ROOT.parent / 'odoo-17.0'
_default_odoo_conf = _default_odoo_root / 'odoo.conf'
_conf_for_addon_paths = (os.getenv('ODOO_CONF_PATH') or os.getenv('EVAL_ODOO_CONF') or os.getenv('ODOO_RC')
                         or (str(_default_odoo_conf) if _default_odoo_conf.is_file() else None))
_ADDON_PATHS = resolve_addon_paths(_conf_for_addon_paths, os.environ, _default_odoo_root, _ROOT)
CORE_ADDONS_PATH = _ADDON_PATHS.core
CUSTOM_ADDONS_PATH = _ADDON_PATHS.custom[0]
CUSTOM_ADDONS_PATHS = _ADDON_PATHS.custom
OCA_SAMPLE_ADDONS_PATH = os.getenv('OCA_SAMPLE_ADDONS_PATH') or None
logging.getLogger(__name__).info(
    'Addon paths (source): core=%s (%s), framework=%s (%s), custom=%s (%s)',
    _ADDON_PATHS.core, _ADDON_PATHS.sources['CORE_ADDONS_PATH'],
    _ADDON_PATHS.framework, _ADDON_PATHS.sources['CORE_FRAMEWORK_ADDONS_PATH'],
    list(_ADDON_PATHS.custom), _ADDON_PATHS.sources['CUSTOM_ADDONS_PATH'])
_ODOO_ROOT = Path(CORE_ADDONS_PATH).parent
_ODOO_VENV_PYTHON = _ODOO_ROOT / '.venv' / 'bin' / 'python'
_ODOO_DEFAULT_CONF = _ODOO_ROOT / 'odoo.conf'
EVAL_ODOO_BIN = os.getenv('EVAL_ODOO_BIN') or str(_ODOO_ROOT / 'odoo-bin')
EVAL_ODOO_PYTHON = os.getenv('EVAL_ODOO_PYTHON') or (str(_ODOO_VENV_PYTHON) if _ODOO_VENV_PYTHON.is_file() else sys.executable)
EVAL_ODOO_CONF = os.getenv('EVAL_ODOO_CONF') or (str(_ODOO_DEFAULT_CONF) if _ODOO_DEFAULT_CONF.is_file() else None)
ODOO_CONF_PATH = os.getenv('ODOO_CONF_PATH') or os.getenv('EVAL_ODOO_CONF') or os.getenv('ODOO_RC') or EVAL_ODOO_CONF
ODOO_DB_DEFAULT, _odoo_db_source = resolve_database(ODOO_CONF_PATH, os.environ)
ODOO_URL_DEFAULT, _odoo_url_source = resolve_odoo_url(ODOO_CONF_PATH, os.environ)
logging.getLogger(__name__).info('Odoo connection defaults (source): url=%s (%s), db=%s (%s)',
    ODOO_URL_DEFAULT, _odoo_url_source, ODOO_DB_DEFAULT, _odoo_db_source)
EVAL_DB_PREFIX = os.getenv('EVAL_DB_PREFIX', 'eval_')
EVAL_INSTANCE_ADMIN_PASSWORD = os.getenv('EVAL_INSTANCE_ADMIN_PASSWORD', 'admin')
EVAL_INSTANCES_DIR = os.getenv('EVAL_INSTANCES_DIR') or str(_ROOT / 'captures' / 'eval_instances')
GRAPH_CACHE_PATH = os.getenv('GRAPH_CACHE_PATH') or str(_ROOT / 'active_graph.json')
GRAPH_TRANSLATION_LANGUAGES = tuple(code.strip() for code in os.getenv('GRAPH_TRANSLATION_LANGUAGES', 'en_US,fr_FR').split(',') if code.strip())
SEMANTIC_INDEX_CACHE_DIR = os.getenv('SEMANTIC_INDEX_CACHE_DIR') or str(_ROOT / 'active_semantic_index')
RAG_DOCS_PATH = os.getenv('RAG_DOCS_PATH') or str(_ROOT / 'document_rag' / 'documents')
DOCUMENT_MAX_TOKENS = int(os.getenv('DOCUMENT_MAX_TOKENS', '2048'))
CORE_FRAMEWORK_ADDONS_PATH = _ADDON_PATHS.framework
SOURCE_LINK_ROOTS = tuple(str(path) for path in (CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, *CUSTOM_ADDONS_PATHS) if path)
USE_RERANKER = os.getenv('USE_RERANKER', 'false').lower() in ('true', '1', 'yes')
VECTOR_SIMILARITY_FLOOR = float(os.getenv('VECTOR_SIMILARITY_FLOOR', '0.20'))
API_HOST = os.getenv('API_HOST', '127.0.0.1')


def parse_cors_origins(raw: str) -> list[str]:
    origins = [origin.strip().rstrip('/') for origin in raw.split(',')]
    return [origin for origin in origins if origin and origin != '*']


CORS_ALLOWED_ORIGINS = parse_cors_origins(os.getenv('CORS_ALLOWED_ORIGINS', ''))
API_PORT = int(os.getenv('API_PORT', '8000'))
LATENCY_BUDGET_P90_SECONDS = float(os.getenv('LATENCY_BUDGET_P90_SECONDS', '12.0'))
LATENCY_BUDGET_RESOLVER_MS = int(os.getenv('LATENCY_BUDGET_RESOLVER_MS', '2000'))
LATENCY_BUDGET_PER_HOP_MS = int(os.getenv('LATENCY_BUDGET_PER_HOP_MS', '3000'))
LATENCY_BUDGET_SYNTHESIS_MS = int(os.getenv('LATENCY_BUDGET_SYNTHESIS_MS', '4000'))
LATENCY_BUDGET_XMLRPC_MS = int(os.getenv('LATENCY_BUDGET_XMLRPC_MS', '5000'))
ORM_RUNTIME_MAX_ROWS = int(os.getenv('ORM_RUNTIME_MAX_ROWS', '100'))
ORM_NAME_SEARCH_LIMIT = int(os.getenv('ORM_NAME_SEARCH_LIMIT', '20'))
ORM_USE_TYPED_RUNTIME = os.getenv('ORM_USE_TYPED_RUNTIME', 'true').lower() in ('true', '1', 'yes')
MAX_MODELS_PER_QUERY = int(os.getenv('MAX_MODELS_PER_QUERY', '3'))
MASSIVE_EXTRACTION_REFUSAL_MSG = 'La demande dépasse le périmètre d\'analyse autorisé.'
PROMPT_INJECTION_REFUSAL_MSG = 'Demande non autorisée : les consignes système et politiques de sécurité ne peuvent pas être altérées ou divulguées.'
