# config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load variables from .env or env file near project root
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
if not os.getenv("GROQ_API_KEY"):
    load_dotenv(_ROOT / "env")

# ── LLM ──────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# GROQ_API_KEYS : rotation automatique des que la cle courante est en rate-limit (core/llm_client.py). Retombe sur GROQ_API_KEY seule si la variable liste n'est pas definie (compat installs a une seule cle).
_groq_keys_raw = os.getenv("GROQ_API_KEYS", "")
GROQ_API_KEYS = [k.strip() for k in _groq_keys_raw.split(",") if k.strip()]
if not GROQ_API_KEYS and GROQ_API_KEY:
    GROQ_API_KEYS = [GROQ_API_KEY]

GROQ_MODEL   = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-14b:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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

# -- Code Intelligence corpus paths ----------------------
CORE_ADDONS_PATH = os.getenv("CORE_ADDONS_PATH") or str(_ROOT.parent / "odoo-17.0" / "addons")
CUSTOM_ADDONS_PATH = os.getenv("CUSTOM_ADDONS_PATH") or str(_ROOT / "odoo_addons")
OCA_SAMPLE_ADDONS_PATH = os.getenv("OCA_SAMPLE_ADDONS_PATH") or None

# -- RAG documentary source path ----------------------
RAG_DOCS_PATH = os.getenv("RAG_DOCS_PATH") or str(_ROOT / "document_rag" / "documents")

CORE_FRAMEWORK_ADDONS_PATH = os.getenv("CORE_FRAMEWORK_ADDONS_PATH") or str(Path(CORE_ADDONS_PATH).parent / "odoo" / "addons")

# ── Retrieval / Re-ranking ────────────────────────────
# Disabled by default to prevent CPU bottlenecks / non-AVX2 freezes.
# Can be enabled explicitly via environment variable USE_RERANKER=true.
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("true", "1", "yes")

VECTOR_SIMILARITY_FLOOR = float(os.getenv("VECTOR_SIMILARITY_FLOOR", "0.20"))

# ── FastAPI ───────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000

# Latency Budgets 
LATENCY_BUDGET_P90_SECONDS = 12.0       # Global per-question budget
LATENCY_BUDGET_RESOLVER_MS = 2000       # resolve_business_term
LATENCY_BUDGET_PER_HOP_MS = 3000        # Each hop (tool call + LLM)
LATENCY_BUDGET_SYNTHESIS_MS = 4000      # Synthesis LLM call
LATENCY_BUDGET_XMLRPC_MS = 5000         # Single XML-RPC call

# ── Security & Extraction Safeguards──────────────────────
MAX_MODELS_PER_QUERY = 3
MASSIVE_EXTRACTION_REFUSAL_MSG = (
    "La demande dépasse le périmètre d'analyse autorisé."
)
PROMPT_INJECTION_REFUSAL_MSG = (
    "Demande non autorisée : les consignes système et politiques de sécurité "
    "ne peuvent pas être altérées ou divulguées."
)