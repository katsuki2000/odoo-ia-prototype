"""Embedding and resolver retrieval use the configured Ollama server."""
from config import settings
from code_intelligence.agent.resolution.semantic_retrieval import build_semantic_embedding_function
from document_rag.vectorstore.embedding_functions import OllamaEmbeddingFunction, resolve_embedding_function


def _configure(monkeypatch):
    monkeypatch.delenv("RESOLVER_SEMANTIC_EMBEDDING_MODEL", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", "http://ollama.example:11434/v1")


def test_resolver_uses_the_configured_server(monkeypatch):
    _configure(monkeypatch)
    provider = resolve_embedding_function()
    assert isinstance(provider, OllamaEmbeddingFunction)
    assert provider.endpoint == "http://ollama.example:11434/v1/embeddings"


def test_business_term_retrieval_uses_the_same_server(monkeypatch):
    _configure(monkeypatch)
    assert isinstance(build_semantic_embedding_function(), OllamaEmbeddingFunction)
