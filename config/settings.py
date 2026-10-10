# config/settings.py
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load variables from .env or env file near project root
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
# ── LLM ──────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local")

# Local-only guard: when true, cloud providers and any endpoint whose host is not in
# LOCAL_ALLOWED_HOSTS are refused (core/llm/local_only.py). A LAN or remote inference
# server is opted into by allow-listing its host here, or by setting LOCAL_ONLY=false.
LOCAL_ONLY = os.getenv("LOCAL_ONLY", "true").lower() in ("true", "1", "yes")
LOCAL_ALLOWED_HOSTS = frozenset(
    host.strip().lower()
    for host in os.getenv("LOCAL_ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",")
    if host.strip()
)

# Local LLM settings (Ollama, vLLM, llama.cpp, LM Studio, LocalAI)
OLLAMA_HOST        = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL       = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", f"{OLLAMA_HOST}/v1")
LOCAL_LLM_MODEL    = os.getenv("LOCAL_LLM_MODEL", OLLAMA_MODEL)
LOCAL_LLM_API_KEY  = os.getenv("LOCAL_LLM_API_KEY", "ollama")

# ── Embeddings ─────────────────────────────────────────
EMBEDDING_BACKEND        = os.getenv("EMBEDDING_BACKEND", "local_light").lower()
EMBEDDING_MODEL_NAME     = os.getenv("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
LOCAL_EMBEDDING_BASE_URL = os.getenv("LOCAL_EMBEDDING_BASE_URL", f"{OLLAMA_HOST}/v1")
LOCAL_EMBEDDING_MODEL    = os.getenv("LOCAL_EMBEDDING_MODEL", "all-minilm:latest")
LOCAL_EMBEDDING_API_KEY  = os.getenv("LOCAL_EMBEDDING_API_KEY", "ollama")

# ── ChromaDB ──────────────────────────────────────────
CHROMA_PATH = os.getenv("CHROMA_PATH") or str(_ROOT / "document_rag" / "vectorstore" / "chroma_db")
DOCS_COLLECTION_NAME = "odoo_docs"

# ── Answer verification (off | report | enforce) ─────────
ANSWER_VERIFIER_MODE = os.getenv("ANSWER_VERIFIER_MODE", "report")

# -- Code Intelligence corpus paths ----------------------
CORE_ADDONS_PATH = os.getenv("CORE_ADDONS_PATH") or str(_ROOT.parent / "odoo-17.0" / "addons")
CUSTOM_ADDONS_PATH = os.getenv("CUSTOM_ADDONS_PATH") or str(_ROOT / "odoo_addons")
OCA_SAMPLE_ADDONS_PATH = os.getenv("OCA_SAMPLE_ADDONS_PATH") or None

_ODOO_ROOT = Path(CORE_ADDONS_PATH).parent
_ODOO_VENV_PYTHON = _ODOO_ROOT / ".venv" / "bin" / "python"
_ODOO_DEFAULT_CONF = _ODOO_ROOT / "odoo.conf"
EVAL_ODOO_BIN = os.getenv("EVAL_ODOO_BIN") or str(_ODOO_ROOT / "odoo-bin")
EVAL_ODOO_PYTHON = os.getenv("EVAL_ODOO_PYTHON") or (
    str(_ODOO_VENV_PYTHON) if _ODOO_VENV_PYTHON.is_file() else sys.executable
)
EVAL_ODOO_CONF = os.getenv("EVAL_ODOO_CONF") or (
    str(_ODOO_DEFAULT_CONF) if _ODOO_DEFAULT_CONF.is_file() else None
)
# Configuration used to resolve addon precedence for the target Odoo instance.
ODOO_CONF_PATH = (
    os.getenv("ODOO_CONF_PATH")
    or os.getenv("EVAL_ODOO_CONF")
    or os.getenv("ODOO_RC")
    or EVAL_ODOO_CONF
)
EVAL_DB_PREFIX = os.getenv("EVAL_DB_PREFIX", "eval_")
EVAL_INSTANCES_DIR = os.getenv("EVAL_INSTANCES_DIR") or str(_ROOT / "captures" / "eval_instances")

GRAPH_CACHE_PATH = os.getenv("GRAPH_CACHE_PATH") or str(_ROOT / "active_graph.json")
SEMANTIC_INDEX_CACHE_DIR = os.getenv("SEMANTIC_INDEX_CACHE_DIR") or str(_ROOT / "active_semantic_index")

# -- RAG documentary source path ----------------------
RAG_DOCS_PATH = os.getenv("RAG_DOCS_PATH") or str(_ROOT / "document_rag" / "documents")
DOCUMENT_MAX_TOKENS = int(os.getenv("DOCUMENT_MAX_TOKENS", "2048"))

CORE_FRAMEWORK_ADDONS_PATH = os.getenv("CORE_FRAMEWORK_ADDONS_PATH") or str(Path(CORE_ADDONS_PATH).parent / "odoo" / "addons")

# ── Retrieval / Re-ranking ────────────────────────────
# Disabled by default to prevent CPU bottlenecks / non-AVX2 freezes.
# Can be enabled explicitly via environment variable USE_RERANKER=true.
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("true", "1", "yes")

VECTOR_SIMILARITY_FLOOR = float(os.getenv("VECTOR_SIMILARITY_FLOOR", "0.20"))

# Deterministic greeting/thanks gate. Off by default: the LLM answers smalltalk.
ENABLE_SMALLTALK_GATE = os.getenv("ENABLE_SMALLTALK_GATE", "false").lower() in (
    "true",
    "1",
    "yes",
)

# ── FastAPI ───────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000

# Latency Budgets 
LATENCY_BUDGET_P90_SECONDS = 12.0       # Global per-question budget
LATENCY_BUDGET_RESOLVER_MS = 2000       # resolve_business_term
LATENCY_BUDGET_PER_HOP_MS = 3000        # Each hop (tool call + LLM)
LATENCY_BUDGET_SYNTHESIS_MS = 4000      # Synthesis LLM call
LATENCY_BUDGET_XMLRPC_MS = 5000         # Single XML-RPC call

# ── ERP runtime (P9) read-only ORM tools ─────────────────
ORM_RUNTIME_MAX_ROWS = int(os.getenv("ORM_RUNTIME_MAX_ROWS", "100"))
ORM_NAME_SEARCH_LIMIT = int(os.getenv("ORM_NAME_SEARCH_LIMIT", "20"))
ORM_RUNTIME_STRICT_IDENTITY = os.getenv("ORM_RUNTIME_STRICT_IDENTITY", "false").lower() in (
    "true",
    "1",
    "yes",
)
# When true, orm_agent_loop binds typed ORM tools (fields_get/search/read/...).
# When false, keeps the legacy domain-specific business tools.
ORM_USE_TYPED_RUNTIME = os.getenv("ORM_USE_TYPED_RUNTIME", "true").lower() in (
    "true",
    "1",
    "yes",
)

# ── Security & Extraction Safeguards──────────────────────
MAX_MODELS_PER_QUERY = 3
MASSIVE_EXTRACTION_REFUSAL_MSG = (
    "La demande dépasse le périmètre d'analyse autorisé."
)
PROMPT_INJECTION_REFUSAL_MSG = (
    "Demande non autorisée : les consignes système et politiques de sécurité "
    "ne peuvent pas être altérées ou divulguées."
)
