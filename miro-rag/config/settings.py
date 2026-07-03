# config/settings.py
import os
from dotenv import load_dotenv

# Load the variables from the .env file
load_dotenv()

# ── LLM ──────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" or "ollama"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL   = "llama-3.1-8b-instant"

OLLAMA_HOST  = "http://localhost:11434"
OLLAMA_MODEL = "hermes3"

# ── ChromaDB ──────────────────────────────────────────
CHROMA_PATH  = "./vectorstore/chroma_db"

# ── FastAPI ───────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000