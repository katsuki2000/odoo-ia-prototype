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
# GROQ_API_KEYS : rotation automatique des que la cle courante est en
# rate-limit (core/llm_client.py). Retombe sur GROQ_API_KEY seule si la
# variable liste n'est pas definie (compat installs a une seule cle).
_groq_keys_raw = os.getenv("GROQ_API_KEYS", "")
GROQ_API_KEYS = [k.strip() for k in _groq_keys_raw.split(",") if k.strip()]
if not GROQ_API_KEYS and GROQ_API_KEY:
    GROQ_API_KEYS = [GROQ_API_KEY]

GROQ_MODEL   = "openai/gpt-oss-20b"

OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-14b:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


OLLAMA_HOST  = "http://localhost:11434"
OLLAMA_MODEL = "gpt-oss:20b"

# ── ChromaDB ──────────────────────────────────────────
CHROMA_PATH  = "./document_rag/vectorstore/chroma_db"

# -- Code Intelligence corpus paths ----------------------
# Machine-dependent: must come from env, never hardcoded (todo/rules.md).
# Fallback is computed relative to this repo's own location, not a
# hardcoded absolute path, so it stays portable on any machine that
# follows the sibling-directory layout documented in README.md
# (~/odoo-ia-prototype next to ~/odoo-17.0).
CORE_ADDONS_PATH = os.getenv("CORE_ADDONS_PATH") or str(_ROOT.parent / "odoo-17.0" / "addons")
CUSTOM_ADDONS_PATH = os.getenv("CUSTOM_ADDONS_PATH") or str(_ROOT / "odoo_addons")

# -- RAG documentary source path ----------------------
# Machine-dependent by convention (todo/rules.md, same pattern as the two
# addons paths above): configurable via env, with a portable fallback
# computed relative to this repo's own location, never a hardcoded
# absolute path. Points at the real (non-fake) documents corpus used by
# the documentary RAG branch (todo/contexte.txt section 351-352):
# document_rag/fake_data/documents/ was the original placeholder location
# and is no longer populated -- document_rag/documents/ is the real
# corpus going forward.
RAG_DOCS_PATH = os.getenv("RAG_DOCS_PATH") or str(_ROOT / "document_rag" / "documents")
# Core FRAMEWORK addons (base, web, ...) -- in a standard Odoo git checkout
# these live under <repo>/odoo/addons/, a SIBLING of <repo>/addons/ (which is
# what CORE_ADDONS_PATH points at, the community addons repo -- account/
# sale/stock live there, but base/web do not). Added 2026-08-27 (contexte.txt
# section 246): custom_* modules that depend on 'base' directly (miro_ai,
# custom_deep_inheritance_security, custom_expense_reimbursement_indirect)
# were silently never getting it loaded, since it was never found under
# CORE_ADDONS_PATH and ci_graph_loader.py had no second root to try.
# Fallback computed relative to CORE_ADDONS_PATH's parent (the repo root),
# matching the standard Odoo checkout layout -- portable, not a hardcoded
# absolute path; override explicitly via env if a given install differs.
CORE_FRAMEWORK_ADDONS_PATH = os.getenv("CORE_FRAMEWORK_ADDONS_PATH") or str(Path(CORE_ADDONS_PATH).parent / "odoo" / "addons")

# ── Retrieval / Re-ranking ────────────────────────────
# Disabled by default to prevent CPU bottlenecks / non-AVX2 freezes.
# Can be enabled explicitly via environment variable USE_RERANKER=true.
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("true", "1", "yes")

# Absolute cosine similarity floor applied in vector_search() before any
# result is allowed into the RRF fusion (todo/contexte.txt section
# 292/293, Bug C root cause: vector_search() had no relevance floor at
# all, only a top_k truncation, so on a small corpus (e.g. ~198 documents)
# it handed back near-arbitrary neighbors even for an unrelated question
# like "Bonjour" -- and RRF's rank-based normalization then dressed those
# irrelevant matches up with high-looking fused scores). Calibrated
# empirically via scripts/_diag_vector_similarity_floor.py on 2026-08-29:
# off-topic queries ("Bonjour", "Hello") topped out around 0.19 raw cosine
# similarity, while a genuinely relevant query ("Comment créer une facture
# ?") stayed above 0.24 even at its 15th-best match -- 0.20 sits in that
# gap with margin on both sides.
# CAUTION -- embedding-backend dependent: measured on the all-MiniLM-L6-v2
# model (384 dim) used by the current EMBEDDING_BACKEND=local_light
# temporary fallback (see chroma_manager.py). NOT portable to
# nomic-embed-text-v1.5 (768 dim, different embedding space) -- re-run the
# diagnostic script and update this value (or override via env) whenever
# EMBEDDING_BACKEND changes.
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
    "La demande dépasse le périmètre d'analyse autorisé. L'analyse de sécurité "
    "est limitée à 3 modèles maximum par requête afin d'éviter l'extraction "
    "massive de données."
)
PROMPT_INJECTION_REFUSAL_MSG = (
    "Demande non autorisée : les consignes système et politiques de sécurité "
    "ne peuvent pas être altérées ou divulguées."
)