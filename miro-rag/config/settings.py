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
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" or "ollama"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL   = "llama-3.1-8b-instant"

OLLAMA_HOST  = "http://localhost:11434"
OLLAMA_MODEL = "hermes3"

# ── ChromaDB ──────────────────────────────────────────
CHROMA_PATH  = "./vectorstore/chroma_db"

# ── Qdrant ────────────────────────────────────────────
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_URL  = os.getenv("QDRANT_URL", f"http://{QDRANT_HOST}:{QDRANT_PORT}")

# ── FastAPI ───────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000