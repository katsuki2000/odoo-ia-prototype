"""Environment and instance configuration.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env')

# ---------------------------------------------------------------------------
# LLM inference server
# ---------------------------------------------------------------------------
def require_inference_server(url):
    if not url:
        raise ValueError('No inference server configured: set OLLAMA_HOST in .env.')
    return url


OLLAMA_HOST = os.getenv('OLLAMA_HOST', '')
_ollama_url = f'{OLLAMA_HOST}/v1' if OLLAMA_HOST else ''
LLM_BASE_URL = _ollama_url
LLM_MODEL = 'gemma4:26b'
LLM_API_KEY = 'ollama'
LLM_TEMPERATURE = 0.2
# 'none' switches reasoning off on models that support it; None keeps the model default.
RAG_REASONING_EFFORT = None
ERP_REASONING_EFFORT = None
LLM_REQUEST_TIMEOUT_SECONDS = 90.0
LLM_MAX_RETRIES = 1

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------
EMBEDDING_BASE_URL = _ollama_url
EMBEDDING_MODEL = 'bge-m3:latest'
EMBEDDING_API_KEY = 'ollama'
EMBEDDING_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# RAG / document retrieval
# ---------------------------------------------------------------------------
CHROMA_PATH = str(_ROOT / 'document_rag' / 'vectorstore' / 'chroma_db')
DOCS_COLLECTION_NAME = 'odoo_docs'
RAG_CHUNK_SIZE = 512
RAG_CHUNK_OVERLAP = 50
DOCUMENT_MAX_TOKENS = 2048
VECTOR_SIMILARITY_FLOOR = 0.20
RAG_VECTOR_WEIGHT = 0.7
RAG_BM25_WEIGHT = 0.3
RAG_RELEVANCE_THRESHOLD = 0.01
RAG_TOP_K = 10
RAG_LEXICAL_SLOTS = 2
RAG_DOCUMENT_EXPANSION_MIN_CHUNKS = 3
RAG_DOCUMENT_EXPANSION_MAX_CHUNKS = 20

# ---------------------------------------------------------------------------
# Odoo connection (secrets and addresses from .env)
# ---------------------------------------------------------------------------
ODOO_SOURCE_PATH = os.getenv('ODOO_SOURCE_PATH') or str(_ROOT.parent / 'odoo-17.0')
ODOO_URL = os.getenv('ODOO_URL') or 'http://localhost:8069'
ODOO_DB = os.getenv('ODOO_DB', '')
ODOO_ADMIN_LOGIN = os.getenv('ODOO_ADMIN_LOGIN') or 'admin'
ODOO_ADMIN_PASSWORD = os.getenv('ODOO_ADMIN_PASSWORD', '')
ODOO_ALLOWED_MODELS = frozenset()

# ---------------------------------------------------------------------------
# ORM agent
# ---------------------------------------------------------------------------
ORM_RUNTIME_MAX_ROWS = 200
ORM_OBSERVATION_MAX_CHARS = 16000
ORM_FIELDS_INDEX_MAX_CHARS = 16000
ORM_SYNTHESIS_MAX_TOKENS = 1024
REACT_RECURSION_LIMIT = 10
ORM_MAX_QUERY_REFUSALS = 2
ORM_NAME_SEARCH_LIMIT = 20
ORM_CONFIDENCE_WITH_DATA = 0.9
ORM_CONFIDENCE_WITHOUT_DATA = 0.5
ANSWER_VERIFIER_MODE = 'enforce'

# ---------------------------------------------------------------------------
# Google Drive corpus (toggle + folder IDs from .env)
# ---------------------------------------------------------------------------
GOOGLE_DRIVE_FOLDER_IDS = tuple(dict.fromkeys(
    value.strip() for value in os.getenv('GOOGLE_DRIVE_FOLDER_IDS', '').split(',') if value.strip()))
GOOGLE_DRIVE_APPROVED_FOR_RAG = os.getenv('GOOGLE_DRIVE_APPROVED_FOR_RAG', '').lower() == 'true'

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv('JWT_SECRET', '')
JWT_ALGORITHM = 'HS256'
JWT_SECRET_MIN_BYTES = 32

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST = os.getenv('API_HOST', '127.0.0.1')
API_PORT = int(os.getenv('API_PORT', '8000'))


def parse_cors_origins(raw: str) -> list[str]:
    origins = [origin.strip().rstrip('/') for origin in raw.split(',')]
    return [origin for origin in origins if origin and origin != '*']


CORS_ALLOWED_ORIGINS = parse_cors_origins(os.getenv('CORS_ALLOWED_ORIGINS', ''))
ASK_JOB_WORKERS = 2
ASK_JOB_MAX_PENDING = 20
ASK_JOB_TTL_SECONDS = 1800

# ---------------------------------------------------------------------------
# Session and display
# ---------------------------------------------------------------------------
SESSION_MAX_COUNT = 1000
QUESTION_PREVIEW_CHARS = 80
OBSERVATION_PREVIEW_CHARS = 300
# Diagnostic file of the agent's reasoning hops (question preview, tool arguments, result excerpts): on unless disabled.
REASONING_TRACE_ENABLED = os.getenv('REASONING_TRACE_ENABLED', 'true').lower() == 'true'
CHAT_HISTORY_MAX_MESSAGES = 10

# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
OUT_OF_SCOPE_ANSWER = (
    "Cette question est hors de mon périmètre. "
    "Je suis spécialisé dans l'assistance interne et les procédures."
)
