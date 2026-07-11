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

# ── Vector store backend ──────────────────────────────
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "qdrant")  # "chroma" or "qdrant"

# Odoo res.company IDs mapped to Qdrant collection names (multi-tenant)
COMPANY_ALPHA_ID = int(os.getenv("COMPANY_ALPHA_ID", "1"))
COMPANY_BETA_ID = int(os.getenv("COMPANY_BETA_ID", "2"))
COMPANY_COLLECTIONS: dict[int, str] = {
    COMPANY_ALPHA_ID: "company_alpha",
    COMPANY_BETA_ID: "company_beta",
}

# Maps Qdrant collection name → fake_data subfolder name.
# Watcher and ingest scripts derive the target collection from the file path:
#   fake_data/<folder_name>/docs/  or  fake_data/<folder_name>/code/
COMPANY_FOLDERS: dict[str, str] = {
    "company_alpha": "company_alpha",
    "company_beta": "company_beta",
}

# Reverse lookup: folder name → company_id (used by watcher path parser)
FOLDER_TO_COMPANY_ID: dict[str, int] = {
    folder: cid for cid, col in COMPANY_COLLECTIONS.items()
    for col_name, folder in COMPANY_FOLDERS.items()
    if col == col_name
}

# ── FastAPI ───────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000