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

GROQ_MODEL   = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-14b:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")

# ── ChromaDB ──────────────────────────────────────────
# BUGFIX (todo/contexte.txt): CHROMA_PATH etait une string relative nue
# ("./document_rag/vectorstore/chroma_db"), non ancree a _ROOT et jamais
# reellement consommee par chroma_manager.py/ingest_all.py (chacun avait
# son propre defaut code en dur, divergent) -- meme classe de violation
# todo/rules.md (no hardcoded paths) deja corrigee pour CORE_ADDONS_PATH/
# RAG_DOCS_PATH. Ancree a _ROOT + env-overridable pour rester coherent
# avec ces deux-la, et desormais reellement le seul chemin utilise par
# les deux points d'entree (ingestion et recherche).
CHROMA_PATH = os.getenv("CHROMA_PATH") or str(_ROOT / "document_rag" / "vectorstore" / "chroma_db")

# -- Code Intelligence corpus paths ----------------------
CORE_ADDONS_PATH = os.getenv("CORE_ADDONS_PATH") or str(_ROOT.parent / "odoo-17.0" / "addons")
CUSTOM_ADDONS_PATH = os.getenv("CUSTOM_ADDONS_PATH") or str(_ROOT / "odoo_addons")

# Bloc P3.1 (todo/contexte.txt section 546, mandat San Goku 2026-09-04) :
# chemin optionnel vers le corpus OCA echantillonne pour le banc de 50
# questions CI (tests/oca_p3_1_question_bank.json). None par defaut --
# aucun changement de comportement pour la production tant que cette
# variable n'est pas positionnee dans .env. Quand elle l'est,
# code_intelligence/ci_graph_loader.py charge en plus les 10 modules OCA
# nommes dans OCA_SAMPLE_MODULE_REPOS (module -> repo), en plus du corpus
# metier reel (CUSTOM_ADDONS_PATH) -- un ajout, jamais un remplacement.
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
    "La demande dépasse le périmètre d'analyse autorisé. L'analyse de sécurité "
    "est limitée à 3 modèles maximum par requête afin d'éviter l'extraction "
    "massive de données."
)
PROMPT_INJECTION_REFUSAL_MSG = (
    "Demande non autorisée : les consignes système et politiques de sécurité "
    "ne peuvent pas être altérées ou divulguées."
)