"""Section 1424: the embedding backend defaults to the inference server, like the LLM; local_light stays opt-in."""
from config import settings
from code_intelligence.agent.semantic_retrieval import build_semantic_embedding_function
from document_rag.vectorstore.embedding_functions import LocalServerEmbeddingFunction, resolve_embedding_function


def _unset(monkeypatch):
    for name in ("EMBEDDING_BACKEND", "RESOLVER_SEMANTIC_EMBEDDING_BACKEND", "RESOLVER_SEMANTIC_EMBEDDING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "LOCAL_EMBEDDING_BASE_URL", "http://localhost:11434/v1")


def test_default_backend_constant_is_the_inference_server():
    assert settings.DEFAULT_EMBEDDING_BACKEND == "local_server"


def test_resolver_uses_the_server_when_backend_is_unset(monkeypatch):
    _unset(monkeypatch)
    provider = resolve_embedding_function()
    assert isinstance(provider, LocalServerEmbeddingFunction)
    assert provider.endpoint == "http://localhost:11434/v1/embeddings"


def test_local_light_remains_available_explicitly(monkeypatch):
    _unset(monkeypatch)
    monkeypatch.setenv("EMBEDDING_BACKEND", "local_light")
    assert resolve_embedding_function() is None


def test_business_term_retrieval_follows_the_same_default(monkeypatch):
    _unset(monkeypatch)
    assert isinstance(build_semantic_embedding_function(), LocalServerEmbeddingFunction)
