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
# "groq" (default, existing behavior) | "openrouter" (new, 2026-08-14 --
# see rag/llm_client.py's module docstring) | "ollama" (NOT YET WIRED UP,
# Bloc 9bis on hold pending local GPU hardware -- get_chat_llm() raises
# NotImplementedError rather than silently falling through).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# NOTE (2026-08-14): Groq deprecated llama-3.1-8b-instant on 2026-06-17,
# recommended migration target openai/gpt-oss-20b -- confirmed via web
# search this session, NOT yet verified against a live call from this
# environment (no execution access). Left UNCHANGED here deliberately --
# this is a separate decision from the LLM_PROVIDER/openrouter work below
# and shouldn't be bundled into it silently. Flagged in contexte.txt /
# todo/etat_reel.md as a likely-already-broken production path on the
# groq provider that needs its own check before relying on it further.
GROQ_MODEL   = "llama-3.1-8b-instant"

# OpenRouter (2026-08-14): interim cloud step for Qwen3-14B, ahead of the
# eventual local Bloc 9bis target -- same model weights, different host.
# Free tier: https://openrouter.ai/settings/keys
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-14b:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

OLLAMA_HOST  = "http://localhost:11434"
OLLAMA_MODEL = "hermes3"

# ── ChromaDB ──────────────────────────────────────────
CHROMA_PATH  = "./vectorstore/chroma_db"

# ── FastAPI ───────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000

# Latency Budgets (Sprint J30-J31)
# p90 = 90th percentile over a benchmark run must be under this value.
LATENCY_BUDGET_P90_SECONDS = 12.0       # Global per-question budget
LATENCY_BUDGET_RESOLVER_MS = 2000       # resolve_business_term
LATENCY_BUDGET_PER_HOP_MS = 3000        # Each hop (tool call + LLM)
LATENCY_BUDGET_SYNTHESIS_MS = 4000      # Synthesis LLM call
LATENCY_BUDGET_XMLRPC_MS = 5000         # Single XML-RPC call

# ── Security & Extraction Safeguards (J32-J33) ──────────────────────
MAX_MODELS_PER_QUERY = 3
MASSIVE_EXTRACTION_REFUSAL_MSG = (
    "La demande dépasse le périmètre d'analyse autorisé. L'analyse de sécurité "
    "est limitée à 3 modèles maximum par requête afin d'éviter l'extraction "
    "massive de données (J32-J33)."
)
PROMPT_INJECTION_REFUSAL_MSG = (
    "Demande non autorisée : les consignes système et politiques de sécurité "
    "ne peuvent pas être altérées ou divulguées (J32-J33)."
)