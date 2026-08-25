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
# NOTE (2026-08-25): tentative de retour vers llama-3.1-8b-instant testee
# et abandonnee -- revert vers openai/gpt-oss-20b confirme (cf section 150
# de contexte.txt). Voir NOTE 2026-08-17 juste en dessous pour le contexte
# complet du choix de gpt-oss-20b.
# NOTE (2026-08-17): Groq deprecation de llama-3.1-8b-instant (annonce
# 2026-06-17) confirmee via recherche web cette session -- migre vers le
# remplacement recommande par Groq, openai/gpt-oss-20b (MoE, 21B total/3.6B
# actif, adapte au tool-calling agentique, tient dans 16GB quantifie --
# correspond au budget materiel local reel de ce projet pour la cible
# eventuelle Ollama Bloc 9bis, choisi plutot que Qwen3-14B cette session
# specifiquement parce que le tier gratuit OpenRouter de Qwen3-14B a
# EGALEMENT ete trouve retire (payant uniquement, $0.10/$0.22 par M
# tokens) et l'utilisateur n'a pas de budget actuellement -- voir
# contexte.txt / todo/etat_reel.md pour l'historique complet de decision).
GROQ_MODEL   = "openai/gpt-oss-20b"

# OpenRouter (2026-08-14): interim cloud step, originally scoped to
# Qwen3-14B ahead of the eventual local Bloc 9bis target -- same model
# weights, different host. Free tier: https://openrouter.ai/settings/keys
# NOTE (2026-08-17): Qwen3-14B's own free tier was found delisted on
# OpenRouter this session (paid-only now) -- LLM_PROVIDER left on "groq"
# (gpt-oss-20b, see above) rather than funding OpenRouter credits the user
# doesn't have right now. This branch stays wired and ready for whenever
# that changes (budget, or OpenRouter re-adds a free Qwen3-14B endpoint).
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-14b:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# NOTE (2026-08-17): switched placeholder from "hermes3" to gpt-oss-20b to
# match the model actually adopted this session (see GROQ_MODEL note above)
# -- keeps the eventual local Ollama target consistent with today's cloud
# testing, rather than silently diverging. Still NOT WIRED UP
# (get_chat_llm() raises NotImplementedError for "ollama" -- Bloc 9bis on
# hold pending local GPU hardware).
OLLAMA_HOST  = "http://localhost:11434"
OLLAMA_MODEL = "gpt-oss:20b"

# ── ChromaDB ──────────────────────────────────────────
CHROMA_PATH  = "./vectorstore/chroma_db"

# ── Retrieval / Re-ranking ────────────────────────────
# Disabled by default to prevent CPU bottlenecks / non-AVX2 freezes.
# Can be enabled explicitly via environment variable USE_RERANKER=true.
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("true", "1", "yes")

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